"""BarramentoRedis contra Redis real. Pula se fora, exceto com EXIGIR_INTEGRACAO=1."""

import asyncio
import os
import uuid
from collections.abc import AsyncIterator

import pytest
from redis.asyncio import Redis

from app.adapters.outbound.barramento.redis import BarramentoRedis
from app.infra.settings import get_settings

pytestmark = pytest.mark.integration


@pytest.fixture
async def redis() -> AsyncIterator[Redis]:
    url = get_settings().redis_url
    cliente = Redis.from_url(url)
    try:
        await cliente.ping()
    except Exception as exc:
        await cliente.aclose()
        msg = f"Redis de teste inacessivel em {url}: {exc!r}"
        if os.environ.get("EXIGIR_INTEGRACAO") == "1":
            pytest.fail(f"EXIGIR_INTEGRACAO=1 e o {msg}", pytrace=False)
        pytest.skip(msg)
    yield cliente
    await cliente.aclose()


async def _receber(barramento: BarramentoRedis, topico: str, n: int) -> list[dict[str, object]]:
    recebidos: list[dict[str, object]] = []
    async for payload in barramento.assinar(topico):
        recebidos.append(payload)
        if len(recebidos) == n:
            break
    return recebidos


async def _esperar_assinante(redis: Redis, topico: str) -> None:
    for _ in range(100):
        contagem = dict(await redis.pubsub_numsub(topico))
        if contagem.get(topico.encode(), contagem.get(topico, 0)) >= 1:
            return
        await asyncio.sleep(0.02)
    raise AssertionError("assinante nao conectou")


async def test_publicar_e_assinar(redis: Redis) -> None:
    barramento = BarramentoRedis(redis)
    topico = f"teste:{uuid.uuid4().hex}"
    tarefa = asyncio.create_task(_receber(barramento, topico, 2))
    await _esperar_assinante(redis, topico)
    await barramento.publicar(topico, {"texto": "olá", "n": 1})
    await barramento.publicar(topico, {"texto": "dois", "n": 2})
    assert await asyncio.wait_for(tarefa, 5) == [
        {"texto": "olá", "n": 1},
        {"texto": "dois", "n": 2},
    ]


async def test_topicos_isolados(redis: Redis) -> None:
    barramento = BarramentoRedis(redis)
    a, b = f"teste:{uuid.uuid4().hex}", f"teste:{uuid.uuid4().hex}"
    tarefa = asyncio.create_task(_receber(barramento, a, 1))
    await _esperar_assinante(redis, a)
    await barramento.publicar(b, {"x": "b"})
    await barramento.publicar(a, {"x": "a"})
    assert await asyncio.wait_for(tarefa, 5) == [{"x": "a"}]
