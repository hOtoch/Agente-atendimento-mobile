"""Handoff com Postgres real: distribui por proporcao, atribui o dono e avisa o vendedor."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.adapters.outbound.db.config import RepositorioVendedoresSql
from app.adapters.outbound.db.models import Evento, Lead, Loja
from app.application.config.entradas import EntradaVendedor
from app.application.painel.eventos import EventoDonoMudou
from app.application.painel.memoria import PublicadorEmMemoria
from app.application.whatsapp import ErroGateway
from app.infra.composicao import montar_aviso_handoff, montar_casos_handoff
from app.infra.settings import Settings

pytestmark = pytest.mark.integration

D = Decimal


class GatewayFalso:
    def __init__(self, *, falhar: bool = False) -> None:
        self.enviados: list[tuple[UUID, str, str]] = []
        self.falhar = falhar

    async def enviar_texto(self, loja_id: UUID, numero: str, texto: str) -> str | None:
        if self.falhar:
            raise ErroGateway("fora do ar")
        self.enviados.append((loja_id, numero, texto))
        return f"ID{len(self.enviados)}"


class RegistroFalso:
    def __init__(self) -> None:
        self.ids: list[str] = []

    async def registrar(self, loja_id: UUID, id_whatsapp: str) -> None:
        self.ids.append(id_whatsapp)


async def _loja(session: AsyncSession, *vendedores: tuple[str, str | None, str]) -> UUID:
    loja = Loja(nome="L")
    session.add(loja)
    await session.flush()
    await RepositorioVendedoresSql(session).substituir(
        loja.id,
        [EntradaVendedor(None, nome, tel, D(peso), True) for nome, tel, peso in vendedores],
    )
    await session.commit()
    return loja.id


async def _leads(session: AsyncSession, loja_id: UUID, n: int) -> list[UUID]:
    leads = [
        Lead(loja_id=loja_id, telefone=f"55119000000{i:02d}", canal="whatsapp") for i in range(n)
    ]
    session.add_all(leads)
    await session.commit()
    return [lead.id for lead in leads]


def _montar(session: AsyncSession, gateway: GatewayFalso, registro: RegistroFalso):  # type: ignore[no-untyped-def]
    assert session.bind is not None
    factory = async_sessionmaker(session.bind, expire_on_commit=False)
    publicador = PublicadorEmMemoria()
    aviso = montar_aviso_handoff(
        factory,
        gateway=gateway,
        registro=registro,
        publicador=publicador,
        settings=Settings(_env_file=None, painel_url="https://painel.exemplo"),
    )
    return aviso, publicador


async def test_handoff_distribui_atribui_dono_e_avisa_o_vendedor(session: AsyncSession) -> None:
    loja = await _loja(session, ("Carla", "(11) 98888-1111", "75"), ("Davi", "11977772222", "25"))
    leads = await _leads(session, loja, 8)
    gateway, registro = GatewayFalso(), RegistroFalso()
    aviso, publicador = _montar(session, gateway, registro)
    casos = montar_casos_handoff(session, publicador=publicador, aviso=aviso)

    for lead in leads:
        await casos.chamar_vendedor(loja, lead, "cliente pediu")

    vendedores = {v.nome: v.id for v in await RepositorioVendedoresSql(session).listar(loja)}
    rows = await session.execute(
        select(Lead.vendedor_id, func.count())
        .where(Lead.loja_id == loja)
        .group_by(Lead.vendedor_id)
    )
    assert dict(rows.all()) == {vendedores["Carla"]: 6, vendedores["Davi"]: 2}
    session.expire_all()

    # cada lead: dono vendedor:<id> e a mensagem no telefone do vendedor escolhido
    telefones = {vendedores["Carla"]: "5511988881111", vendedores["Davi"]: "5511977772222"}
    por_lead = {t: n for _, n, t in gateway.enviados}
    assert len(gateway.enviados) == 8 and len(registro.ids) == 8
    for lead in leads:
        row = (await session.execute(select(Lead).where(Lead.id == lead))).scalar_one()
        assert row.dono == "vendedor" and row.vendedor_id is not None
        enviados = [(n, t) for _, n, t in gateway.enviados if f"lead={lead}" in t]
        assert len(enviados) == 1
        assert enviados[0][0] == telefones[row.vendedor_id]
        assert f"https://painel.exemplo/conversas?lead={lead}" in enviados[0][1]
    assert por_lead  # ha textos
    donos = [
        e.dono
        for _, e in publicador.publicados
        if isinstance(e, EventoDonoMudou) and e.vendedor_id is not None
    ]
    assert len(donos) == 8 and all(d.startswith("vendedor:") for d in donos)


async def test_registra_evento_de_distribuicao(session: AsyncSession) -> None:
    loja = await _loja(session, ("Carla", "11988881111", "100"))
    (lead,) = await _leads(session, loja, 1)
    aviso, publicador = _montar(session, GatewayFalso(), RegistroFalso())
    await montar_casos_handoff(session, publicador=publicador, aviso=aviso).chamar_vendedor(
        loja, lead, "m"
    )
    payloads = (
        (
            await session.execute(
                select(Evento.payload).where(Evento.lead_id == lead, Evento.tipo == "dono_mudou")
            )
        )
        .scalars()
        .all()
    )
    assert any(p.get("origem") == "distribuicao" for p in payloads)


async def test_sem_vendedor_fica_aguardando(session: AsyncSession) -> None:
    loja = await _loja(session)
    (lead,) = await _leads(session, loja, 1)
    gateway = GatewayFalso()
    aviso, publicador = _montar(session, gateway, RegistroFalso())
    await montar_casos_handoff(session, publicador=publicador, aviso=aviso).chamar_vendedor(
        loja, lead, "m"
    )
    row = (await session.execute(select(Lead).where(Lead.id == lead))).scalar_one()
    await session.refresh(row)
    assert (row.dono, row.vendedor_id) == ("vendedor", None)
    assert gateway.enviados == []


async def test_whatsapp_fora_mantem_a_atribuicao(session: AsyncSession) -> None:
    loja = await _loja(session, ("Carla", "11988881111", "100"))
    (lead,) = await _leads(session, loja, 1)
    aviso, publicador = _montar(session, GatewayFalso(falhar=True), RegistroFalso())
    await montar_casos_handoff(session, publicador=publicador, aviso=aviso).chamar_vendedor(
        loja, lead, "m"
    )
    row = (await session.execute(select(Lead).where(Lead.id == lead))).scalar_one()
    await session.refresh(row)
    assert row.dono == "vendedor" and row.vendedor_id is not None


async def test_fluxo_completo_pelo_processar_conversa_sem_travar(
    db_url: str, session: AsyncSession
) -> None:
    """A IA chama o vendedor no turno; o gancho real distribui e avisa (sem deadlock de sessao)."""
    from datetime import UTC, date, datetime

    from app.adapters.outbound.barramento.memoria import BarramentoEmMemoria
    from app.adapters.outbound.canal.webchat import WebChatAdapter
    from app.adapters.outbound.db.conversas import RepositorioConversasSql
    from app.adapters.outbound.llm.fake import FakeLLM, RespostaRoteirizada
    from app.application.canal import Canal, MensagemEntrada, TipoMensagem
    from app.application.llm import ChamadaFerramenta
    from app.infra.composicao import montar_processar_conversa
    from app.infra.seed import LOJA_DEMO_ID, semear

    await semear(db_url)
    lead_id, conversa = await RepositorioConversasSql(session).obter_ou_criar(
        LOJA_DEMO_ID, Canal.WEBCHAT, "s1"
    )
    await RepositorioConversasSql(session).registrar_entrada(
        conversa,
        MensagemEntrada(
            LOJA_DEMO_ID, Canal.WEBCHAT, "ext1", "s1", TipoMensagem.TEXTO, "quero um vendedor",
            None, datetime.now(UTC),
        ),
    )  # fmt: skip
    llm = FakeLLM(
        [
            RespostaRoteirizada(
                chamadas=[ChamadaFerramenta("t1", "chamar_vendedor", {"motivo": "pediu humano"})]
            ),
            RespostaRoteirizada(texto="Já chamei um vendedor para você."),
            RespostaRoteirizada(texto="Cliente pediu atendimento humano."),
        ]
    )
    gateway, registro = GatewayFalso(), RegistroFalso()
    aviso, publicador = _montar(session, gateway, registro)
    caso = montar_processar_conversa(
        session,
        llm=llm,
        canais={Canal.WEBCHAT: WebChatAdapter(BarramentoEmMemoria())},
        painel=publicador,
        aviso_handoff=aviso,
        hoje=lambda: date(2026, 11, 20),
    )
    await caso(conversa)

    row = (await session.execute(select(Lead).where(Lead.id == lead_id))).scalar_one()
    await session.refresh(row)
    assert row.dono == "vendedor" and row.vendedor_id is not None
    ((_, numero, texto),) = gateway.enviados
    assert numero.startswith("55") and f"lead={lead_id}" in texto
    assert "pediu humano" in texto
