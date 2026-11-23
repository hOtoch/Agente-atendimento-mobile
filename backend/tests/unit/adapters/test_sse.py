"""Formatacao SSE e heartbeat."""

import asyncio
from collections.abc import AsyncIterator

import anyio
import pytest

from app.adapters.inbound.http.sse import SSE_HEADERS
from app.adapters.inbound.http.webchat import eventos_sse


def test_headers_impedem_proxy_de_comprimir_ou_segurar_o_stream() -> None:
    """Proxy com gzip (o rewrite /api do Next, tuneis) segura o SSE ate o fim sem no-transform."""
    diretivas = {d.strip() for d in SSE_HEADERS["Cache-Control"].split(",")}
    assert {"no-cache", "no-transform"} <= diretivas
    assert SSE_HEADERS["X-Accel-Buffering"] == "no"


async def _lento() -> AsyncIterator[dict[str, object]]:
    await asyncio.sleep(0.15)
    yield {"texto": "oi"}


async def test_emite_heartbeat_enquanto_espera_e_depois_a_mensagem() -> None:
    saida = [bloco async for bloco in eventos_sse(_lento(), heartbeat_s=0.05)]
    assert saida[0] == ": heartbeat\n\n"
    assert any(b.startswith("data: ") and '"texto": "oi"' in b for b in saida)
    assert saida[-1].endswith("\n\n")


def _fonte_que_espera(fechou: asyncio.Event) -> AsyncIterator[dict[str, object]]:
    async def gerar() -> AsyncIterator[dict[str, object]]:
        try:
            while True:
                await asyncio.sleep(10)
                yield {"texto": "nunca"}
        finally:
            fechou.set()

    return gerar()


async def _consumir(fonte: AsyncIterator[dict[str, object]]) -> None:
    async for _ in eventos_sse(fonte, heartbeat_s=0.01):
        pass


async def test_cliente_desconecta_no_meio_da_espera_fecha_a_fonte_sem_erro() -> None:
    fechou = asyncio.Event()
    tarefa = asyncio.create_task(_consumir(_fonte_que_espera(fechou)))
    await asyncio.sleep(0.05)
    tarefa.cancel()
    with pytest.raises(asyncio.CancelledError):
        await tarefa
    assert fechou.is_set()


async def test_desconexao_sob_cancel_scope_do_starlette_fecha_a_fonte() -> None:
    """O Starlette cancela o stream por um cancel scope do anyio, que recancela cada await."""
    fechou = asyncio.Event()
    async with anyio.create_task_group() as grupo:
        grupo.start_soon(_consumir, _fonte_que_espera(fechou))
        await anyio.sleep(0.05)
        grupo.cancel_scope.cancel()
    assert fechou.is_set()
