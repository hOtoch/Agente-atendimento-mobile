"""Worker arq. Comando (a partir de backend/): `uv run arq app.infra.worker.WorkerSettings`.

`processar_conversa` aplica o debounce e a trava (`ProcessarQuandoQuieto`) e chama o hook
`ctx["processar"]`: por padrao o `ProcessarConversa` real (`composicao.criar_processador`);
testes injetam o proprio hook (ex.: com FakeLLM) em `ctx` antes do startup.

`followup_cron` (a cada 5 min) manda o follow-up automatico aos leads parados via o hook
`ctx["followup"]` (por padrao `composicao.criar_followups`, montado na primeira rodada).

`sincronizar_erp_cron` (a cada 5 min) sincroniza o estoque das lojas com ERP ativo cujo intervalo
venceu, via `ctx["sincronizar_erp"]` (por padrao `composicao.criar_sincronizador_erp`).
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from arq import cron
from arq.connections import RedisSettings
from arq.worker import func

from app.adapters.outbound.barramento.redis import BarramentoRedis
from app.adapters.outbound.db.session import criar_engine, criar_session_factory
from app.application.agendamento import ProcessarQuandoQuieto
from app.infra.composicao import (
    criar_agendador,
    criar_followups,
    criar_gancho_handoff,
    criar_processador,
    criar_sincronizador_erp,
)
from app.infra.fila import FUNCAO_PROCESSAR, RelogioParede, TravaRedis
from app.infra.settings import get_settings

log = logging.getLogger(__name__)


async def iniciar(ctx: dict[str, Any]) -> None:
    """Monta o caso de uso. `ctx["processar"]` ja presente substitui o orquestrador real."""
    settings = get_settings()
    redis = ctx["redis"]
    if "processar" not in ctx:
        engine = criar_engine(settings.database_url)
        ctx["engine"] = engine
        factory = criar_session_factory(engine)
        ctx["factory"] = factory
        barramento = BarramentoRedis(redis)
        ctx["processar"] = criar_processador(
            factory,
            redis=redis,
            settings=settings,
            barramento=barramento,
            aviso_handoff=criar_gancho_handoff(
                factory, redis=redis, barramento=barramento, settings=settings
            ),
        )
    ctx["caso"] = ProcessarQuandoQuieto(
        agendador=criar_agendador(redis, settings),
        trava=TravaRedis(redis),
        relogio=RelogioParede(),
        processar=ctx["processar"],
        janela_s=settings.fila_janela_s,
        trava_ttl_s=settings.fila_trava_ttl_s,
    )


async def followup_cron(ctx: dict[str, Any]) -> int:
    """Rodada do follow-up automatico. Devolve quantas mensagens enviou."""
    if "followup" not in ctx:
        settings = get_settings()
        if "factory" not in ctx:
            engine = criar_engine(settings.database_url)
            ctx["engine"] = engine
            ctx["factory"] = criar_session_factory(engine)
        ctx["followup"] = criar_followups(ctx["factory"], redis=ctx["redis"], settings=settings)
    enviados: int = await ctx["followup"]()
    if enviados:
        log.info("follow-up automatico: %s mensagem(ns) enviada(s)", enviados)
    return enviados


async def sincronizar_erp_cron(ctx: dict[str, Any]) -> int:
    """Rodada da sincronizacao do estoque do ERP. Devolve quantas lojas sincronizou."""
    if "sincronizar_erp" not in ctx:
        settings = get_settings()
        if "factory" not in ctx:
            engine = criar_engine(settings.database_url)
            ctx["engine"] = engine
            ctx["factory"] = criar_session_factory(engine)
        ctx["sincronizar_erp"] = criar_sincronizador_erp(ctx["factory"])
    sincronizadas: int = await ctx["sincronizar_erp"]()
    if sincronizadas:
        log.info("sincronizacao do ERP: %s loja(s) sincronizada(s)", sincronizadas)
    return sincronizadas


async def encerrar(ctx: dict[str, Any]) -> None:
    engine = ctx.get("engine")
    if engine is not None:
        await engine.dispose()


async def processar_conversa(ctx: dict[str, Any], conversa_id: str) -> None:
    await ctx["caso"](UUID(conversa_id))


class WorkerSettings:
    functions = [func(processar_conversa, name=FUNCAO_PROCESSAR, keep_result=0)]
    cron_jobs = [
        cron(
            followup_cron,
            name="followup_automatico",
            minute=set(range(0, 60, 5)),
            run_at_startup=False,
            unique=True,
            keep_result=0,
            timeout=300,
        ),
        cron(
            sincronizar_erp_cron,
            name="sincronizar_estoque_erp",
            minute=set(range(0, 60, 5)),
            run_at_startup=False,
            unique=True,
            keep_result=0,
            timeout=600,
        ),
    ]
    on_startup = iniciar
    on_shutdown = encerrar
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
