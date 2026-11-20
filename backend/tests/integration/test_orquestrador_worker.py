"""POST no webchat -> arq -> worker (burst) -> ProcessarConversa (FakeLLM) -> topico do webchat."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from uuid import UUID

import httpx
import pytest
from arq.connections import ArqRedis
from arq.worker import Worker, func
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.adapters.outbound.barramento.redis import BarramentoRedis
from app.adapters.outbound.canal.webchat import topico_webchat
from app.adapters.outbound.db.models import Lead
from app.adapters.outbound.llm.fake import FakeLLM, RespostaRoteirizada
from app.application.agendamento import ProcessarQuandoQuieto
from app.application.llm import ChamadaFerramenta
from app.infra.composicao import criar_processador
from app.infra.dependencias import get_agendar, get_barramento, get_session
from app.infra.fila import FUNCAO_PROCESSAR, AgendadorArq, RelogioParede, TravaRedis
from app.infra.seed import LOJA_DEMO_ID, semear
from app.infra.settings import get_settings
from app.main import app
from tests.integration.conftest import aplicar_migrations

pytestmark = pytest.mark.integration

JANELA = 0.4


@pytest.fixture
async def ambiente(
    db_url: str, redis_pool: ArqRedis, prefixo_redis: str
) -> AsyncIterator[tuple[httpx.AsyncClient, async_sessionmaker[AsyncSession], AgendadorArq, str]]:
    await aplicar_migrations(db_url)
    await semear(db_url)
    engine = create_async_engine(db_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    fila = f"{prefixo_redis}fila"
    agendador = AgendadorArq(redis_pool, janela_s=JANELA, prefixo=prefixo_redis, nome_fila=fila)

    async def _sessao() -> AsyncIterator[AsyncSession]:
        async with factory() as s:
            yield s

    app.dependency_overrides[get_session] = _sessao
    app.dependency_overrides[get_barramento] = lambda: BarramentoRedis(redis_pool)
    app.dependency_overrides[get_agendar] = lambda: agendador.agendar
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        yield c, factory, agendador, fila
    app.dependency_overrides.clear()
    await engine.dispose()


def _worker(
    redis_pool: ArqRedis,
    factory: async_sessionmaker[AsyncSession],
    agendador: AgendadorArq,
    fila: str,
    prefixo: str,
    llm: FakeLLM,
) -> Worker:
    processar = criar_processador(
        factory,
        redis=redis_pool,
        settings=get_settings(),
        llm=llm,
        barramento=BarramentoRedis(redis_pool),
    )
    caso = ProcessarQuandoQuieto(
        agendador=agendador,
        trava=TravaRedis(redis_pool, prefixo=prefixo),
        relogio=RelogioParede(),
        processar=processar,
        janela_s=JANELA,
        espera_trava_s=0.1,
    )

    async def processar_conversa(ctx: dict[str, object], conversa_id: str) -> None:
        await caso(UUID(conversa_id))

    return Worker(
        functions=[func(processar_conversa, name=FUNCAO_PROCESSAR, keep_result=0)],
        redis_pool=redis_pool,
        queue_name=fila,
        burst=True,
        poll_delay=0.05,
        handle_signals=False,
    )


async def test_post_no_webchat_vira_resposta_no_topico(
    ambiente: tuple[httpx.AsyncClient, async_sessionmaker[AsyncSession], AgendadorArq, str],
    redis_pool: ArqRedis,
    prefixo_redis: str,
) -> None:
    cliente, factory, agendador, fila = ambiente
    sessao = "sessao-e2e"
    interesse = {"modelo": "iPhone 16", "capacidade": "128GB", "cor": None}
    llm = FakeLLM(
        [
            RespostaRoteirizada(
                chamadas=[
                    ChamadaFerramenta("t1", "registrar_interesse", interesse),
                    ChamadaFerramenta("t2", "consultar_estoque", interesse),
                ]
            ),
            RespostaRoteirizada(texto="Temos o iPhone 16 128GB! Vai dar algum aparelho na troca?"),
        ]
    )

    ouvinte = BarramentoRedis(redis_pool).assinar(topico_webchat(LOJA_DEMO_ID, sessao))
    recebida = asyncio.create_task(anext(ouvinte))
    await asyncio.sleep(0.3)  # da tempo do SUBSCRIBE chegar ao Redis

    for n, texto in enumerate(["oi", "quero um iphone 16 128"]):
        r = await cliente.post(
            f"/webchat/{LOJA_DEMO_ID}/sessoes/{sessao}/mensagens",
            json={"id_cliente": f"m{n}", "tipo": "texto", "texto": texto},
        )
        assert r.status_code == 202
        await asyncio.sleep(0.05)

    worker = _worker(redis_pool, factory, agendador, fila, prefixo_redis, llm)
    await worker.main()
    try:
        msg = await asyncio.wait_for(recebida, timeout=10)
    finally:
        recebida.cancel()
        await ouvinte.aclose()  # type: ignore[attr-defined]

    assert msg["texto"] == "Temos o iPhone 16 128GB! Vai dar algum aparelho na troca?"
    assert len(llm.chamadas) == 2  # as duas mensagens viraram UM atendimento
    async with factory() as s:
        etapa = (await s.execute(select(Lead.etapa))).scalar_one()
    assert etapa == "interesse_identificado"


async def test_api_enfileira_e_worker_processa_separadamente(
    ambiente: tuple[httpx.AsyncClient, async_sessionmaker[AsyncSession], AgendadorArq, str],
    redis_pool: ArqRedis,
    prefixo_redis: str,
) -> None:
    cliente, factory, agendador, fila = ambiente
    r = await cliente.post(
        f"/webchat/{LOJA_DEMO_ID}/sessoes/s-sep/mensagens",
        json={"id_cliente": "m1", "tipo": "texto", "texto": "oi"},
    )
    conversa_id = UUID(r.json()["conversa_id"])
    assert await redis_pool.zcard(fila) == 1  # job enfileirado pela API
    assert await agendador.pendente(conversa_id) is not None

    llm = FakeLLM([RespostaRoteirizada(texto="Oi! Qual iPhone você procura?")])
    await _worker(redis_pool, factory, agendador, fila, prefixo_redis, llm).main()
    assert len(llm.chamadas) == 1
    assert await agendador.pendente(conversa_id) is None  # concluido
