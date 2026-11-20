"""Formatacao SSE compartilhada (chat web e painel)."""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import AsyncIterator

import anyio

HEARTBEAT_S = 15.0

SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


async def eventos_sse(
    mensagens: AsyncIterator[dict[str, object]], heartbeat_s: float = HEARTBEAT_S
) -> AsyncIterator[str]:
    """Converte mensagens em blocos SSE, com comentario de heartbeat nos intervalos."""
    pendente: asyncio.Future[dict[str, object]] = asyncio.ensure_future(anext(mensagens))
    try:
        while True:
            await asyncio.wait({pendente}, timeout=heartbeat_s)
            if not pendente.done():
                yield ": heartbeat\n\n"
                continue
            try:
                payload = pendente.result()
            except StopAsyncIteration:
                return
            yield f"data: {json.dumps(payload)}\n\n"
            pendente = asyncio.ensure_future(anext(mensagens))
    finally:
        # Cliente desconectou (ou a fonte acabou). O `anext` pendente ainda roda DENTRO do
        # gerador: so da para fechar a fonte depois que ele terminar de cancelar. O shield
        # impede que o cancel scope do Starlette recancele estes awaits de limpeza.
        with anyio.CancelScope(shield=True):
            pendente.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await pendente
            aclose = getattr(mensagens, "aclose", None)
            if aclose is not None:
                await aclose()
