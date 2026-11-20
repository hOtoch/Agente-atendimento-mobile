"""Worker arq. Comando (a partir de backend/): `uv run arq app.infra.worker.WorkerSettings`.

`processar_conversa` so aplica o debounce e a trava (`ProcessarQuandoQuieto`); o trabalho de
verdade e um hook injetavel (`ctx["processar"]`), que o orquestrador do agente (#24) vai
fornecer. Por ora o hook so registra em log.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from arq.connections import RedisSettings
from arq.worker import func

from app.application.agendamento import ProcessarQuandoQuieto
from app.infra.fila import FUNCAO_PROCESSAR, AgendadorArq, RelogioParede, TravaRedis
from app.infra.settings import get_settings

log = logging.getLogger(__name__)


async def registrar_em_log(conversa_id: UUID) -> None:
    log.info("processar conversa %s (hook padrao: so registra)", conversa_id)


async def iniciar(ctx: dict[str, Any]) -> None:
    """Monta o caso de uso. `ctx["processar"]` substitui o hook padrao (orquestrador do agente)."""
    settings = get_settings()
    redis = ctx["redis"]
    ctx["caso"] = ProcessarQuandoQuieto(
        agendador=AgendadorArq(redis, janela_s=settings.fila_janela_s),
        trava=TravaRedis(redis),
        relogio=RelogioParede(),
        processar=ctx.get("processar", registrar_em_log),
        janela_s=settings.fila_janela_s,
        trava_ttl_s=settings.fila_trava_ttl_s,
    )


async def processar_conversa(ctx: dict[str, Any], conversa_id: str) -> None:
    await ctx["caso"](UUID(conversa_id))


class WorkerSettings:
    functions = [func(processar_conversa, name=FUNCAO_PROCESSAR, keep_result=0)]
    on_startup = iniciar
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
