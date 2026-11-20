"""Worker arq. Comando (a partir de backend/): `uv run arq app.infra.worker.WorkerSettings`.

`processar_conversa` aplica o debounce e a trava (`ProcessarQuandoQuieto`) e chama o hook
`ctx["processar"]`: por padrao o `ProcessarConversa` real (`composicao.criar_processador`);
testes injetam o proprio hook (ex.: com FakeLLM) em `ctx` antes do startup.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from arq.connections import RedisSettings
from arq.worker import func

from app.adapters.outbound.db.session import criar_engine, criar_session_factory
from app.application.agendamento import ProcessarQuandoQuieto
from app.infra.composicao import criar_agendador, criar_processador
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
        ctx["processar"] = criar_processador(
            criar_session_factory(engine), redis=redis, settings=settings
        )
    ctx["caso"] = ProcessarQuandoQuieto(
        agendador=criar_agendador(redis, settings),
        trava=TravaRedis(redis),
        relogio=RelogioParede(),
        processar=ctx["processar"],
        janela_s=settings.fila_janela_s,
        trava_ttl_s=settings.fila_trava_ttl_s,
    )


async def encerrar(ctx: dict[str, Any]) -> None:
    engine = ctx.get("engine")
    if engine is not None:
        await engine.dispose()


async def processar_conversa(ctx: dict[str, Any], conversa_id: str) -> None:
    await ctx["caso"](UUID(conversa_id))


class WorkerSettings:
    functions = [func(processar_conversa, name=FUNCAO_PROCESSAR, keep_result=0)]
    on_startup = iniciar
    on_shutdown = encerrar
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
