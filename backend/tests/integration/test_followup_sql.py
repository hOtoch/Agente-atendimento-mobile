"""Follow-up com Postgres real: candidatos, tentativas como eventos e envio de ponta a ponta."""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from uuid import UUID

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.adapters.outbound.db.followup import RepositorioConfigFollowupSql, RepositorioFollowupSql
from app.adapters.outbound.db.models import Conversa, Evento, Lead, Loja, Mensagem
from app.adapters.outbound.llm.fake import FakeLLM, RespostaRoteirizada
from app.application.canal import Canal, MensagemSaida
from app.domain.followup import ConfigFollowup
from app.domain.kanban import Etapa
from app.infra.composicao import montar_enviar_followups

pytestmark = pytest.mark.integration

# sexta 12:00 em Sao Paulo
AGORA = datetime(2026, 11, 20, 15, 0, tzinfo=UTC)


class CanalFalso:
    def __init__(self) -> None:
        self.enviadas: list[MensagemSaida] = []

    async def enviar(self, msg: MensagemSaida) -> None:
        self.enviadas.append(msg)


async def _loja(session: AsyncSession, *, ligado: bool = True) -> UUID:
    loja = Loja(nome="L")
    session.add(loja)
    await session.flush()
    await RepositorioConfigFollowupSql(session).salvar(
        loja.id,
        ConfigFollowup(
            ligado=ligado,
            horas_por_etapa={Etapa.INTERESSE_QUALIFICADO: 2},
            hora_inicio=time(9, 0),
            hora_fim=time(18, 0),
        ),
    )
    await session.commit()
    return loja.id


async def _lead(
    session: AsyncSession,
    loja_id: UUID,
    *,
    dono: str = "ia",
    parado_h: float = 3,
    ultima: str = "saida",
    etapa: Etapa = Etapa.INTERESSE_QUALIFICADO,
    telefone: str = "5511999990000",
) -> tuple[UUID, UUID]:
    lead = Lead(loja_id=loja_id, telefone=telefone, canal="webchat", etapa=etapa.value, dono=dono)
    session.add(lead)
    await session.flush()
    conversa = Conversa(loja_id=loja_id, lead_id=lead.id, canal="webchat")
    session.add(conversa)
    await session.flush()
    fim = AGORA - timedelta(hours=parado_h)
    for direcao, autor, em in (
        ("entrada", "cliente", fim - timedelta(minutes=1)),
        (ultima, "cliente" if ultima == "entrada" else "ia", fim),
    ):
        session.add(
            Mensagem(
                loja_id=loja_id,
                conversa_id=conversa.id,
                canal="webchat",
                direcao=direcao,
                autor=autor,
                tipo="texto",
                conteudo="oi",
                criado_em=em,
            )
        )
    await session.commit()
    return lead.id, conversa.id


async def _rodar(factory: async_sessionmaker[AsyncSession], canal: CanalFalso, llm: FakeLLM) -> int:
    async with factory() as s:
        caso = montar_enviar_followups(
            s, llm=llm, canais={Canal.WEBCHAT: canal}, agora=lambda: AGORA
        )
        return await caso()


async def test_lead_parado_recebe_um_followup_gravado_e_nao_recebe_outro(
    session: AsyncSession,
) -> None:
    factory = async_sessionmaker(session.bind, expire_on_commit=False)
    loja = await _loja(session)
    lead_id, conversa_id = await _lead(session, loja)
    canal = CanalFalso()
    llm = FakeLLM([RespostaRoteirizada(texto="Oi! Ainda quer o iPhone 16?")] * 3)

    assert await _rodar(factory, canal, llm) == 1
    assert [m.texto for m in canal.enviadas] == ["Oi! Ainda quer o iPhone 16?"]
    assert canal.enviadas[0].destinatario == "5511999990000"
    assert llm.chamadas[0].ferramentas == []

    session.expire_all()
    eventos = (
        (
            await session.execute(
                select(Evento).where(Evento.tipo == "followup", Evento.lead_id == lead_id)
            )
        )
        .scalars()
        .all()
    )
    assert len(eventos) == 1
    assert eventos[0].payload == {"tentativa": 1, "etapa": "interesse_qualificado"}
    assert eventos[0].criado_em == AGORA
    saidas = (
        await session.execute(
            select(func.count())
            .select_from(Mensagem)
            .where(
                Mensagem.conversa_id == conversa_id,
                Mensagem.autor == "ia",
                Mensagem.direcao == "saida",
            )
        )
    ).scalar_one()
    assert saidas == 2  # a original + o follow-up

    # novas rodadas no mesmo instante: nada
    assert await _rodar(factory, canal, llm) == 0
    assert len(canal.enviadas) == 1
    assert len(llm.chamadas) == 1


async def test_dono_vendedor_e_fora_do_horario_nao_recebem(session: AsyncSession) -> None:
    factory = async_sessionmaker(session.bind, expire_on_commit=False)
    loja = await _loja(session)
    await _lead(session, loja, dono="vendedor", telefone="1")
    await _lead(session, loja, ultima="entrada", telefone="2")  # cliente falou por ultimo
    await _lead(session, loja, parado_h=1, telefone="3")  # parado ha menos de 2 h
    await _lead(session, loja, etapa=Etapa.INTERESSE_IDENTIFICADO, telefone="4")  # sem config
    canal = CanalFalso()
    llm = FakeLLM([])
    assert await _rodar(factory, canal, llm) == 0
    assert canal.enviadas == [] and llm.chamadas == []

    # fora do horario: 22:00 UTC = 19:00 em Sao Paulo
    await _lead(session, loja, parado_h=-7 + 3, telefone="5")
    async with factory() as s:
        caso = montar_enviar_followups(
            s,
            llm=llm,
            canais={Canal.WEBCHAT: canal},
            agora=lambda: datetime(2026, 11, 20, 22, 0, tzinfo=UTC),
        )
        assert await caso() == 0
    assert canal.enviadas == []


async def test_loja_desligada_nao_envia_e_tentativas_reiniciam_com_resposta_do_cliente(
    session: AsyncSession,
) -> None:
    factory = async_sessionmaker(session.bind, expire_on_commit=False)
    desligada = await _loja(session, ligado=False)
    await _lead(session, desligada)
    canal, llm = CanalFalso(), FakeLLM([RespostaRoteirizada(texto="Oi!")] * 3)
    assert await _rodar(factory, canal, llm) == 0

    loja = await _loja(session)
    lead_id, conversa_id = await _lead(session, loja)
    assert await _rodar(factory, canal, llm) == 1
    # o cliente responde depois do follow-up: o ciclo recomeca (tentativas = 0)
    session.add(
        Mensagem(
            loja_id=loja,
            conversa_id=conversa_id,
            canal="webchat",
            direcao="entrada",
            autor="cliente",
            tipo="texto",
            conteudo="voltei",
            criado_em=AGORA + timedelta(seconds=1),
        )
    )
    await session.commit()
    async with factory() as s:
        candidatos = await RepositorioFollowupSql(s).listar_candidatos(
            loja, [Etapa.INTERESSE_QUALIFICADO], datetime.now(UTC) + timedelta(days=1)
        )
    (c,) = [x for x in candidatos if x.lead_id == lead_id]
    assert c.tentativas == 0
    assert c.ultimo_followup_em == AGORA


async def test_config_sem_gravacao_e_padrao_desligada(session: AsyncSession) -> None:
    loja = Loja(nome="X")
    session.add(loja)
    await session.commit()
    repo = RepositorioConfigFollowupSql(session)
    assert (await repo.obter(loja.id)).ligado is False
    assert await repo.lojas_com_followup_ligado() == []
