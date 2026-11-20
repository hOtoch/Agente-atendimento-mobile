"""Transcricao SQL e o fluxo do `ProcessarConversa` com Postgres real e FakeLLM."""

from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.outbound.barramento.memoria import BarramentoEmMemoria
from app.adapters.outbound.canal.webchat import WebChatAdapter, topico_webchat
from app.adapters.outbound.db.conversas import RepositorioConversasSql
from app.adapters.outbound.db.models import Evento, Lead, Mensagem
from app.adapters.outbound.db.transcricao import RepositorioTranscricaoSql
from app.adapters.outbound.llm.fake import FakeLLM, RespostaRoteirizada
from app.application.agente.transcricao import CursorEntrada
from app.application.canal import Canal, MensagemEntrada, TipoMensagem
from app.application.llm import (
    BlocoTexto,
    ChamadaFerramenta,
    LLMIndisponivel,
    MensagemLLM,
    ResultadoFerramenta,
)
from app.infra.composicao import montar_processar_conversa
from app.infra.seed import LOJA_DEMO_ID, semear

pytestmark = pytest.mark.integration

HOJE = date(2026, 11, 20)
BRUTO = [
    {"type": "thinking", "thinking": "hmm", "signature": "c2ln"},
    {"type": "text", "text": "ok"},
]


async def _conversa(session: AsyncSession, loja_id: UUID, contato: str = "s1") -> tuple[UUID, UUID]:
    return await RepositorioConversasSql(session).obter_ou_criar(loja_id, Canal.WEBCHAT, contato)


async def _entrada(
    session: AsyncSession, loja_id: UUID, conversa_id: UUID, texto: str, contato: str = "s1"
) -> None:
    await RepositorioConversasSql(session).registrar_entrada(
        conversa_id,
        MensagemEntrada(
            loja_id, Canal.WEBCHAT, uuid4().hex, contato, TipoMensagem.TEXTO, texto, None,
            datetime.now(UTC),
        ),
    )  # fmt: skip


async def test_transcricao_sql_ordem_cursor_e_ida_e_volta(session: AsyncSession) -> None:
    await semear(session.bind.url.render_as_string(hide_password=False))  # type: ignore[union-attr]
    _, conversa = await _conversa(session, LOJA_DEMO_ID)
    repo = RepositorioTranscricaoSql(session)
    assert await repo.listar(conversa) == []
    assert await repo.consumido_ate(conversa) is None

    m1 = [MensagemLLM("user", [BlocoTexto("oi")]), MensagemLLM("system", [BlocoTexto("ESTADO")])]
    cursor = CursorEntrada(datetime(2026, 11, 20, 12, 0, 0, 123456, tzinfo=UTC), uuid4())
    await repo.acrescentar(conversa, m1, consumido_ate=cursor)
    m2 = [
        MensagemLLM("assistant", [ChamadaFerramenta("t1", "x", {"a": 1})], bruto=BRUTO),
        MensagemLLM("user", [ResultadoFerramenta("t1", "{}", False)]),
    ]
    await repo.acrescentar(conversa, m2)
    assert await repo.listar(conversa) == [*m1, *m2]
    assert await repo.consumido_ate(conversa) == cursor
    c2 = CursorEntrada(datetime(2026, 11, 21, tzinfo=UTC), uuid4())
    await repo.marcar_consumidas(conversa, c2)
    assert await repo.consumido_ate(conversa) == c2
    assert len(await repo.listar(conversa)) == 4

    # outra conversa nao se mistura
    _, outra = await _conversa(session, LOJA_DEMO_ID, "s2")
    assert await repo.listar(outra) == []
    # nunca ha edicao: so inserts, sequenciais
    eventos = (
        (await session.execute(select(Evento.payload).where(Evento.tipo == "llm_mensagem")))
        .scalars()
        .all()
    )
    assert sorted(e["seq"] for e in eventos) == [1, 2, 3, 4]


async def test_fluxo_com_banco_real_e_fake_llm(db_url: str, session: AsyncSession) -> None:
    await semear(db_url)
    lead_id, conversa = await _conversa(session, LOJA_DEMO_ID)
    await _entrada(session, LOJA_DEMO_ID, conversa, "oi, quero um iphone 16 128")
    await _entrada(session, LOJA_DEMO_ID, conversa, "de preferencia preto")
    interesse = {"modelo": "iPhone 16", "capacidade": "128GB", "cor": None}
    llm = FakeLLM(
        [
            RespostaRoteirizada(
                chamadas=[
                    ChamadaFerramenta("t1", "registrar_interesse", interesse),
                    ChamadaFerramenta("t2", "consultar_estoque", interesse),
                ]
            ),
            RespostaRoteirizada(texto="Temos sim! Você vai dar algum aparelho na troca?"),
            RespostaRoteirizada(texto="Fechado, e como pretende pagar?"),
        ]
    )
    barramento = BarramentoEmMemoria()
    publicadas = barramento.assinar(topico_webchat(LOJA_DEMO_ID, "s1"))
    caso = montar_processar_conversa(
        session, llm=llm, canais={Canal.WEBCHAT: WebChatAdapter(barramento)}, hoje=lambda: HOJE
    )
    await caso(conversa)

    msg = await anext(publicadas)
    assert msg["texto"] == "Temos sim! Você vai dar algum aparelho na troca?"
    # as duas entradas viraram UM turno user
    primeiro = llm.chamadas[0].mensagens
    assert [m.papel for m in primeiro] == ["user", "system"]
    assert len(primeiro[0].blocos) == 2

    etapa = (await session.execute(select(Lead.etapa).where(Lead.id == lead_id))).scalar_one()
    assert etapa == "interesse_identificado"
    saidas = (
        (await session.execute(select(Mensagem).where(Mensagem.direcao == "saida"))).scalars().all()
    )
    assert [s.conteudo for s in saidas] == [msg["texto"]]
    tipos = (await session.execute(select(Evento.tipo))).scalars().all()
    for esperado in ("llm_mensagem", "ferramenta", "etapa_mudou", "llm_uso"):
        assert esperado in tipos

    # segundo turno: o historico e a reproducao exata + novidades; nada reprocessado
    await caso(conversa)
    await _entrada(session, LOJA_DEMO_ID, conversa, "nao tenho troca")
    await caso(conversa)
    anterior = llm.chamadas[1].mensagens
    ultimo = llm.chamadas[2].mensagens
    assert ultimo[: len(anterior)] == anterior
    assert len([m for m in ultimo if m.papel == "system"]) == 2


async def test_falha_do_llm_com_banco_real_faz_handoff(db_url: str, session: AsyncSession) -> None:
    await semear(db_url)
    lead_id, conversa = await _conversa(session, LOJA_DEMO_ID)
    await _entrada(session, LOJA_DEMO_ID, conversa, "oi")
    barramento = BarramentoEmMemoria()
    publicadas = barramento.assinar(topico_webchat(LOJA_DEMO_ID, "s1"))
    llm = FakeLLM([RespostaRoteirizada(erro=LLMIndisponivel("fora"))])
    caso = montar_processar_conversa(
        session, llm=llm, canais={Canal.WEBCHAT: WebChatAdapter(barramento)}, hoje=lambda: HOJE
    )
    await caso(conversa)
    assert "especialista" in str(await anext(publicadas))
    etapa = (await session.execute(select(Lead.etapa).where(Lead.id == lead_id))).scalar_one()
    assert etapa == "com_o_vendedor"
