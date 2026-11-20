"""Formatacao SSE e heartbeat."""

import asyncio
from collections.abc import AsyncIterator

from app.adapters.inbound.http.webchat import eventos_sse


async def _lento() -> AsyncIterator[dict[str, object]]:
    await asyncio.sleep(0.15)
    yield {"texto": "oi"}


async def test_emite_heartbeat_enquanto_espera_e_depois_a_mensagem() -> None:
    saida = [bloco async for bloco in eventos_sse(_lento(), heartbeat_s=0.05)]
    assert saida[0] == ": heartbeat\n\n"
    assert any(b.startswith("data: ") and '"texto": "oi"' in b for b in saida)
    assert saida[-1].endswith("\n\n")
