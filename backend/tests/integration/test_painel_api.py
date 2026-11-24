"""API do painel (kanban, detalhe, movimentos, handoff, mensagem do vendedor) e SSE de eventos.

App real + Postgres isolado; barramento em memoria (o SSE le o mesmo barramento que publica).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.adapters.outbound.barramento.memoria import BarramentoEmMemoria
from app.adapters.outbound.barramento.painel import topico_painel
from app.adapters.outbound.canal.webchat import topico_webchat
from app.adapters.outbound.db.models import Conversa, Evento, Ficha, Lead, Mensagem, Vendedor
from app.application.agente.estado import EstadoAtendimento
from app.domain.aparelho import Capacidade, ModeloAparelho
from app.domain.ficha import Ficha as FichaDominio
from app.infra.dependencias import get_agendar, get_barramento, get_session
from app.main import app
from tests.integration.conftest import aplicar_migrations
from tests.integration.lojas import criar_loja_no_banco

pytestmark = pytest.mark.integration


class Ambiente:
    def __init__(
        self,
        client: httpx.AsyncClient,
        barramento: BarramentoEmMemoria,
        factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self.client = client
        self.barramento = barramento
        self.factory = factory

    async def loja(self) -> str:
        return await criar_loja_no_banco("Loja Painel")

    async def vendedor(self, loja: str, nome: str = "Carla") -> UUID:
        async with self.factory() as s:
            v = Vendedor(loja_id=UUID(loja), nome=nome)
            s.add(v)
            await s.commit()
            return v.id

    async def lead(
        self,
        loja: str,
        *,
        telefone: str = "sessao-1",
        canal: str = "webchat",
        etapa: str = "novo_contato",
        dono: str = "ia",
        vendedor_id: UUID | None = None,
        estado: EstadoAtendimento | None = None,
        nome: str | None = None,
    ) -> tuple[UUID, UUID]:
        """Cria lead + conversa (+ ficha). Devolve (lead_id, conversa_id)."""
        async with self.factory() as s:
            lead = Lead(
                loja_id=UUID(loja),
                telefone=telefone,
                canal=canal,
                etapa=etapa,
                dono=dono,
                vendedor_id=vendedor_id,
                nome=nome,
            )
            s.add(lead)
            await s.flush()
            conversa = Conversa(loja_id=UUID(loja), lead_id=lead.id, canal=canal)
            s.add(conversa)
            if estado is not None:
                s.add(
                    Ficha(loja_id=UUID(loja), lead_id=lead.id, versao=1, dados=estado.para_dict())
                )
            await s.commit()
            return lead.id, conversa.id

    async def mensagem(
        self, loja: str, conversa: UUID, *, direcao: str, texto: str, ha_s: int = 0
    ) -> None:
        async with self.factory() as s:
            s.add(
                Mensagem(
                    loja_id=UUID(loja),
                    conversa_id=conversa,
                    canal="webchat",
                    direcao=direcao,
                    autor="cliente" if direcao == "entrada" else "ia",
                    tipo="texto",
                    conteudo=texto,
                    criado_em=datetime.now(UTC) - timedelta(seconds=ha_s),
                )
            )
            await s.commit()

    async def ler_sse(self, url: str, durante: Any, fechar: str) -> list[dict[str, Any]]:
        """Abre o stream, roda `durante()` e fecha o topico (ASGITransport so entrega no fim)."""

        async def ler() -> list[str]:
            async with self.client.stream("GET", url) as r:
                assert r.status_code == 200
                assert r.headers["content-type"].startswith("text/event-stream")
                return [linha async for linha in r.aiter_lines()]

        tarefa = asyncio.create_task(ler())
        await asyncio.sleep(0.3)
        await durante()
        self.barramento.fechar(fechar)
        linhas = await asyncio.wait_for(tarefa, 5)
        return [json.loads(x[5:]) for x in linhas if x.startswith("data:")]


@pytest.fixture
async def amb(db_url: str) -> AsyncIterator[Ambiente]:
    await aplicar_migrations(db_url)
    engine = create_async_engine(db_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    barramento = BarramentoEmMemoria()

    async def _sessao() -> AsyncIterator[AsyncSession]:
        async with factory() as s:
            try:
                yield s
            except BaseException:
                await s.rollback()
                raise

    async def _agendar(_: UUID) -> None:
        return None

    app.dependency_overrides[get_session] = _sessao
    app.dependency_overrides[get_barramento] = lambda: barramento
    app.dependency_overrides[get_agendar] = lambda: _agendar
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        yield Ambiente(c, barramento, factory)
    app.dependency_overrides.clear()
    await engine.dispose()


def _estado_iphone() -> EstadoAtendimento:
    ficha = FichaDominio.vazia().com_interesse(
        modelo=ModeloAparelho.de("iPhone 16", "Apple"), capacidade=Capacidade(128)
    )
    return EstadoAtendimento(
        ficha=ficha,
        ultima_proposta={"preco_aparelho": "4830.00", "forma_escolhida": {"total_pago": "5339.40"}},
    )


# --- listagem ---------------------------------------------------------------------------------


async def test_lista_leads_por_etapa_com_dados_do_card(amb: Ambiente) -> None:
    loja = await amb.loja()
    vend = await amb.vendedor(loja)
    novo, _ = await amb.lead(loja, telefone="s1", nome="Ana")
    qualificado, _ = await amb.lead(
        loja,
        telefone="5511999990000",
        etapa="interesse_qualificado",
        estado=_estado_iphone(),
        dono="vendedor",
        vendedor_id=vend,
    )

    r = await amb.client.get(f"/lojas/{loja}/leads")

    assert r.status_code == 200
    etapas = r.json()["etapas"]
    assert [e["etapa"] for e in etapas] == [
        "novo_contato",
        "interesse_identificado",
        "interesse_qualificado",
        "com_o_vendedor",
        "venda_fechada",
    ]
    assert etapas[0]["nome"] == "Novo contato"
    assert [c["id"] for c in etapas[0]["leads"]] == [str(novo)]
    assert etapas[1]["leads"] == []
    card = etapas[2]["leads"][0]
    assert card["id"] == str(qualificado)
    assert card["telefone"] == "5511999990000"
    assert card["aparelho_desejado"] == "iPhone 16 128GB"
    assert card["valor_estimado"] == "5339.40"
    assert card["dono"] == f"vendedor:{vend}"
    assert card["vendedor_id"] == str(vend)
    assert card["vendedor_nome"] == "Carla"
    assert card["canal"] == "webchat"
    assert card["etapa"] == "interesse_qualificado"
    assert card["etapa_desde"]  # fallback: criacao do lead


async def test_etapa_desde_usa_o_ultimo_evento_de_etapa(amb: Ambiente) -> None:
    loja = await amb.loja()
    lead, _ = await amb.lead(loja, etapa="interesse_identificado")
    quando = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)
    async with amb.factory() as s:
        s.add(
            Evento(
                loja_id=UUID(loja),
                lead_id=lead,
                tipo="etapa_mudou",
                payload={"para": "interesse_identificado"},
                criado_em=quando,
            )
        )
        await s.commit()
    r = await amb.client.get(f"/lojas/{loja}/leads")
    card = r.json()["etapas"][1]["leads"][0]
    assert datetime.fromisoformat(card["etapa_desde"]) == quando


async def test_listagem_isola_lojas_e_404_para_loja_inexistente(amb: Ambiente) -> None:
    a, b = await amb.loja(), await amb.loja()
    await amb.lead(a, telefone="da-a")
    r = await amb.client.get(f"/lojas/{b}/leads")
    assert all(e["leads"] == [] for e in r.json()["etapas"])
    assert (await amb.client.get(f"/lojas/{uuid4()}/leads")).status_code == 404


# --- detalhe ----------------------------------------------------------------------------------


async def test_detalhe_traz_ficha_pendencias_mensagens_e_eventos(amb: Ambiente) -> None:
    loja = await amb.loja()
    lead, conversa = await amb.lead(loja, estado=_estado_iphone())
    await amb.mensagem(loja, conversa, direcao="entrada", texto="oi", ha_s=10)
    await amb.mensagem(loja, conversa, direcao="saida", texto="ola!", ha_s=5)
    async with amb.factory() as s:
        s.add(Evento(loja_id=UUID(loja), lead_id=lead, tipo="etapa_mudou", payload={"x": 1}))
        await s.commit()

    r = await amb.client.get(f"/lojas/{loja}/leads/{lead}")

    assert r.status_code == 200
    d = r.json()
    assert d["card"]["id"] == str(lead)
    assert d["ficha"]["interesse"]["capacidade"] == 128
    assert "estoque_confirmado" in d["pendencias"]
    assert [(m["autor"], m["direcao"], m["texto"]) for m in d["mensagens"]] == [
        ("cliente", "entrada", "oi"),
        ("ia", "saida", "ola!"),
    ]
    assert [e["tipo"] for e in d["eventos"]] == ["etapa_mudou"]
    assert d["eventos"][0]["payload"] == {"x": 1}
    assert d["proposta"]["preco_aparelho"] == "4830.00"
    assert d["handoff_solicitado"] is False


async def test_detalhe_404_para_lead_inexistente_ou_de_outra_loja(amb: Ambiente) -> None:
    a, b = await amb.loja(), await amb.loja()
    lead, _ = await amb.lead(a)
    assert (await amb.client.get(f"/lojas/{a}/leads/{uuid4()}")).status_code == 404
    assert (await amb.client.get(f"/lojas/{b}/leads/{lead}")).status_code == 404


# --- mover etapa ------------------------------------------------------------------------------


async def test_mover_etapa_valido_atualiza_registra_evento_e_responde_o_card(
    amb: Ambiente,
) -> None:
    loja = await amb.loja()
    lead, _ = await amb.lead(loja)

    r = await amb.client.post(f"/lojas/{loja}/leads/{lead}/etapa", json={"etapa": "com_o_vendedor"})

    assert r.status_code == 200
    assert r.json()["etapa"] == "com_o_vendedor"
    async with amb.factory() as s:
        assert (await s.get(Lead, lead)).etapa == "com_o_vendedor"  # type: ignore[union-attr]
        eventos = (await s.execute(select(Evento).where(Evento.lead_id == lead))).scalars().all()
    assert [(e.tipo, e.payload["ator"], e.payload["para"]) for e in eventos] == [
        ("etapa_mudou", "vendedor", "com_o_vendedor")
    ]


@pytest.mark.parametrize(
    ("etapa_atual", "destino"),
    [
        ("novo_contato", "novo_contato"),  # mesma etapa
        ("venda_fechada", "novo_contato"),  # etapa final
        ("venda_fechada", "com_o_vendedor"),
    ],
)
async def test_mover_etapa_invalido_devolve_409_e_nao_muda_nada(
    amb: Ambiente, etapa_atual: str, destino: str
) -> None:
    loja = await amb.loja()
    lead, _ = await amb.lead(loja, etapa=etapa_atual)

    r = await amb.client.post(f"/lojas/{loja}/leads/{lead}/etapa", json={"etapa": destino})

    assert r.status_code == 409
    assert r.json()["erros"][0]["caminho"] == "etapa"
    assert r.json()["erros"][0]["mensagem"]
    async with amb.factory() as s:
        assert (await s.get(Lead, lead)).etapa == etapa_atual  # type: ignore[union-attr]
        assert (await s.execute(select(Evento))).scalars().all() == []


async def test_mover_etapa_desconhecida_e_422_e_lead_inexistente_404(amb: Ambiente) -> None:
    loja = await amb.loja()
    lead, _ = await amb.lead(loja)
    r = await amb.client.post(f"/lojas/{loja}/leads/{lead}/etapa", json={"etapa": "voando"})
    assert r.status_code == 422
    r = await amb.client.post(
        f"/lojas/{loja}/leads/{uuid4()}/etapa", json={"etapa": "com_o_vendedor"}
    )
    assert r.status_code == 404


async def test_evento_de_etapa_chega_no_sse_apos_a_mudanca(amb: Ambiente) -> None:
    loja = await amb.loja()
    lead, _ = await amb.lead(loja)

    async def mover() -> None:
        r = await amb.client.post(
            f"/lojas/{loja}/leads/{lead}/etapa", json={"etapa": "com_o_vendedor"}
        )
        assert r.status_code == 200

    eventos = await amb.ler_sse(f"/lojas/{loja}/eventos", mover, topico_painel(UUID(loja)))

    assert [e["evento"] for e in eventos] == ["EtapaMudou"]
    assert eventos[0]["lead_id"] == str(lead)
    assert (eventos[0]["de"], eventos[0]["para"], eventos[0]["ator"]) == (
        "novo_contato",
        "com_o_vendedor",
        "vendedor",
    )


async def test_sse_404_para_loja_inexistente(amb: Ambiente) -> None:
    assert (await amb.client.get(f"/lojas/{uuid4()}/eventos")).status_code == 404


async def test_sse_nao_entrega_eventos_de_outra_loja(amb: Ambiente) -> None:
    a, b = await amb.loja(), await amb.loja()
    lead_b, _ = await amb.lead(b)

    async def mover_na_b() -> None:
        await amb.client.post(f"/lojas/{b}/leads/{lead_b}/etapa", json={"etapa": "com_o_vendedor"})

    eventos = await amb.ler_sse(f"/lojas/{a}/eventos", mover_na_b, topico_painel(UUID(a)))
    assert eventos == []


# --- resetar conversa ------------------------------------------------------------------------


async def test_resetar_apaga_a_conversa_e_publica_lead_removido(amb: Ambiente) -> None:
    loja = await amb.loja()
    lead, conversa = await amb.lead(loja, estado=_estado_iphone())
    await amb.mensagem(loja, conversa, direcao="entrada", texto="quero um iphone", ha_s=10)

    async def resetar() -> None:
        r = await amb.client.delete(f"/lojas/{loja}/leads/{lead}")
        assert r.status_code == 204

    eventos = await amb.ler_sse(f"/lojas/{loja}/eventos", resetar, topico_painel(UUID(loja)))

    assert [(e["evento"], e["lead_id"]) for e in eventos] == [("LeadRemovido", str(lead))]
    assert (await amb.client.get(f"/lojas/{loja}/leads/{lead}")).status_code == 404
    kanban = (await amb.client.get(f"/lojas/{loja}/leads")).json()
    assert all(c["id"] != str(lead) for col in kanban["etapas"] for c in col["leads"])


async def test_resetar_lead_inexistente_ou_de_outra_loja_e_404(amb: Ambiente) -> None:
    a, b = await amb.loja(), await amb.loja()
    lead_b, _ = await amb.lead(b)
    assert (await amb.client.delete(f"/lojas/{a}/leads/{lead_b}")).status_code == 404
    assert (await amb.client.delete(f"/lojas/{a}/leads/{uuid4()}")).status_code == 404
    assert (await amb.client.get(f"/lojas/{b}/leads/{lead_b}")).status_code == 200


# --- assumir / devolver -----------------------------------------------------------------------


async def test_assumir_e_devolver_persistem_o_dono_e_publicam_dono_mudou(amb: Ambiente) -> None:
    loja = await amb.loja()
    vend = await amb.vendedor(loja)
    lead, _ = await amb.lead(loja)

    async def fluxo() -> None:
        r = await amb.client.post(
            f"/lojas/{loja}/leads/{lead}/assumir", json={"vendedor_id": str(vend)}
        )
        assert r.status_code == 200
        assert r.json()["dono"] == f"vendedor:{vend}"
        assert r.json()["vendedor_nome"] == "Carla"
        async with amb.factory() as s:
            row = await s.get(Lead, lead)
            assert (row.dono, row.vendedor_id) == ("vendedor", vend)  # type: ignore[union-attr]
        r = await amb.client.post(f"/lojas/{loja}/leads/{lead}/devolver")
        assert r.status_code == 200
        assert r.json()["dono"] == "ia"
        async with amb.factory() as s:
            row = await s.get(Lead, lead)
            assert (row.dono, row.vendedor_id) == ("ia", vend)  # type: ignore[union-attr]

    eventos = await amb.ler_sse(f"/lojas/{loja}/eventos", fluxo, topico_painel(UUID(loja)))

    assert [(e["evento"], e["dono"]) for e in eventos] == [
        ("DonoMudou", f"vendedor:{vend}"),
        ("DonoMudou", "ia"),
    ]
    assert eventos[0]["vendedor_id"] == str(vend)


async def test_assumir_com_vendedor_inexistente_404_e_conflitos_409(amb: Ambiente) -> None:
    loja = await amb.loja()
    vend = await amb.vendedor(loja)
    outro = await amb.vendedor(loja, "Dani")
    lead, _ = await amb.lead(loja)
    url = f"/lojas/{loja}/leads/{lead}"

    r = await amb.client.post(f"{url}/assumir", json={"vendedor_id": str(uuid4())})
    assert r.status_code == 404
    assert (await amb.client.post(f"{url}/devolver")).status_code == 409  # ja e da IA

    assert (
        await amb.client.post(f"{url}/assumir", json={"vendedor_id": str(vend)})
    ).status_code == 200
    r = await amb.client.post(f"{url}/assumir", json={"vendedor_id": str(outro)})
    assert r.status_code == 409


# --- mensagem como vendedor -------------------------------------------------------------------


async def test_vendedor_envia_mensagem_persiste_entrega_no_webchat_e_publica(
    amb: Ambiente,
) -> None:
    loja = await amb.loja()
    vend = await amb.vendedor(loja)
    lead, conversa = await amb.lead(loja, telefone="sessao-9", dono="vendedor", vendedor_id=vend)
    entrega = amb.barramento.assinar(topico_webchat(UUID(loja), "sessao-9"))

    async def enviar() -> None:
        r = await amb.client.post(
            f"/lojas/{loja}/leads/{lead}/mensagens", json={"texto": "Oi, sou a Carla"}
        )
        assert r.status_code == 201
        corpo = r.json()
        assert corpo["enviada"] is True
        assert corpo["mensagem"]["autor"] == "vendedor"
        assert corpo["mensagem"]["direcao"] == "saida"
        assert corpo["mensagem"]["texto"] == "Oi, sou a Carla"

    eventos = await amb.ler_sse(f"/lojas/{loja}/eventos", enviar, topico_painel(UUID(loja)))

    assert [e["evento"] for e in eventos] == ["MensagemNova"]
    assert (eventos[0]["autor"], eventos[0]["lead_id"], eventos[0]["conversa_id"]) == (
        "vendedor",
        str(lead),
        str(conversa),
    )
    assert (await anext(entrega))["texto"] == "Oi, sou a Carla"  # type: ignore[call-overload]
    async with amb.factory() as s:
        m = (await s.execute(select(Mensagem).where(Mensagem.conversa_id == conversa))).scalar_one()
    assert (m.autor, m.direcao, m.conteudo) == ("vendedor", "saida", "Oi, sou a Carla")
    d = (await amb.client.get(f"/lojas/{loja}/leads/{lead}")).json()
    assert d["mensagens"][-1]["autor"] == "vendedor"


async def test_enviar_mensagem_sem_assumir_409_e_texto_vazio_422(amb: Ambiente) -> None:
    loja = await amb.loja()
    lead, _ = await amb.lead(loja)
    url = f"/lojas/{loja}/leads/{lead}/mensagens"
    assert (await amb.client.post(url, json={"texto": "oi"})).status_code == 409
    assert (await amb.client.post(url, json={"texto": "   "})).status_code == 422
    assert (
        await amb.client.post(f"/lojas/{loja}/leads/{uuid4()}/mensagens", json={"texto": "oi"})
    ).status_code == 404


async def test_mensagem_em_canal_sem_adaptador_e_persistida_com_enviada_false(
    amb: Ambiente,
) -> None:
    loja = await amb.loja()
    vend = await amb.vendedor(loja)
    lead, _ = await amb.lead(
        loja, telefone="5511", canal="instagram", dono="vendedor", vendedor_id=vend
    )
    r = await amb.client.post(f"/lojas/{loja}/leads/{lead}/mensagens", json={"texto": "oi"})
    assert r.status_code == 201
    assert r.json()["enviada"] is False


async def test_mensagem_do_cliente_pelo_webchat_publica_mensagem_nova_no_painel(
    amb: Ambiente,
) -> None:
    loja = await amb.loja()

    async def cliente_fala() -> None:
        sessao = (await amb.client.post(f"/webchat/{loja}/sessoes")).json()["sessao"]
        r = await amb.client.post(
            f"/webchat/{loja}/sessoes/{sessao}/mensagens",
            json={"id_cliente": "c1", "tipo": "texto", "texto": "quero um iphone"},
        )
        assert r.status_code == 202

    eventos = await amb.ler_sse(f"/lojas/{loja}/eventos", cliente_fala, topico_painel(UUID(loja)))

    assert [e["evento"] for e in eventos] == ["MensagemNova"]
    assert (eventos[0]["autor"], eventos[0]["direcao"], eventos[0]["texto"]) == (
        "cliente",
        "entrada",
        "quero um iphone",
    )
    async with amb.factory() as s:
        m = (await s.execute(select(Mensagem))).scalar_one()
    assert m.autor == "cliente"


# --- handoff: resumo e conversa aguardando vendedor -------------------------------------------


async def test_detalhe_traz_o_resumo_do_handoff_quando_a_ia_chamou_o_vendedor(
    amb: Ambiente,
) -> None:
    loja = await amb.loja()
    lead, _ = await amb.lead(
        loja,
        dono="vendedor",
        estado=EstadoAtendimento(handoff_solicitado=True, motivo_handoff="falha_llm"),
    )
    resumo = {
        "motivo": "A IA ficou indisponível e passou a conversa para o vendedor",
        "aparelho_desejado": "iPhone 16 128GB",
        "troca": "iPhone 13 128GB",
        "valor_troca": "1200.00",
        "proposta": None,
        "valor_proposta": None,
        "forma_pagamento": None,
        "data_prevista": "2026-11-25",
        "pendencias": ["bandeira do cartão"],
        "observacoes": "Cliente decidido.",
        "gerado_em": "2026-11-20T15:00:00+00:00",
    }
    async with amb.factory() as s:
        s.add(Evento(loja_id=UUID(loja), lead_id=lead, tipo="handoff_resumo", payload=resumo))
        await s.commit()

    d = (await amb.client.get(f"/lojas/{loja}/leads/{lead}")).json()

    assert d["card"]["dono"] == "vendedor" and d["card"]["vendedor_id"] is None
    r = d["resumo_handoff"]
    assert r["aparelho_desejado"] == "iPhone 16 128GB"
    assert r["valor_troca"] == "1200.00" and r["data_prevista"] == "2026-11-25"
    assert r["observacoes"] == "Cliente decidido."
    assert r["pendencias"] == ["bandeira do cartão"]


async def test_detalhe_sem_handoff_da_ia_tem_resumo_nulo(amb: Ambiente) -> None:
    loja = await amb.loja()
    lead, _ = await amb.lead(loja)
    d = (await amb.client.get(f"/lojas/{loja}/leads/{lead}")).json()
    assert d["resumo_handoff"] is None


async def test_qualquer_vendedor_assume_a_conversa_aguardando_vendedor(amb: Ambiente) -> None:
    loja = await amb.loja()
    vend = await amb.vendedor(loja)
    lead, _ = await amb.lead(loja, dono="vendedor", vendedor_id=None)

    r = await amb.client.post(
        f"/lojas/{loja}/leads/{lead}/assumir", json={"vendedor_id": str(vend)}
    )

    assert r.status_code == 200
    assert r.json()["dono"] == f"vendedor:{vend}"
    async with amb.factory() as s:
        row = await s.get(Lead, lead)
        assert (row.dono, row.vendedor_id) == ("vendedor", vend)  # type: ignore[union-attr]


async def test_devolver_grava_o_contexto_do_vendedor_na_transcricao_e_limpa_o_handoff(
    amb: Ambiente,
) -> None:
    loja = await amb.loja()
    vend = await amb.vendedor(loja)
    lead, conversa = await amb.lead(
        loja,
        dono="vendedor",
        vendedor_id=vend,
        estado=EstadoAtendimento(handoff_solicitado=True, motivo_handoff="quer fechar"),
    )
    await amb.mensagem(loja, conversa, direcao="saida", texto="vou chamar alguém", ha_s=20)
    async with amb.factory() as s:
        s.add(
            Mensagem(
                loja_id=UUID(loja),
                conversa_id=conversa,
                canal="webchat",
                direcao="saida",
                autor="vendedor",
                tipo="texto",
                conteudo="Qual a bateria do seu aparelho?",
            )
        )
        await s.commit()

    r = await amb.client.post(f"/lojas/{loja}/leads/{lead}/devolver")

    assert r.status_code == 200 and r.json()["dono"] == "ia"
    async with amb.factory() as s:
        textos = [
            e.payload
            for e in (
                await s.execute(
                    select(Evento).where(Evento.lead_id == lead, Evento.tipo == "llm_mensagem")
                )
            ).scalars()
        ]
        assert len(textos) == 1 and textos[0]["papel"] == "system"
        assert "Vendedor: Qual a bateria do seu aparelho?" in textos[0]["blocos"][0]["texto"]
    d = (await amb.client.get(f"/lojas/{loja}/leads/{lead}")).json()
    assert d["handoff_solicitado"] is False and d["resumo_handoff"] is None
