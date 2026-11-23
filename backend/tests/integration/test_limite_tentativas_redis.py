"""LimiteTentativasRedis contra Redis real, com prefixo proprio por teste."""

import asyncio
from collections.abc import AsyncIterator

import pytest
from arq.connections import ArqRedis

from app.adapters.outbound.auth.limite import LimiteTentativasRedis
from app.application.auth.modelos import ChaveLimite

pytestmark = pytest.mark.integration

EMAIL = ChaveLimite("email:a@b.com", 3)
IP = ChaveLimite("ip:1.2.3.4", 5)


@pytest.fixture
async def limite(redis_pool: ArqRedis, prefixo_redis: str) -> AsyncIterator[LimiteTentativasRedis]:
    yield LimiteTentativasRedis(redis_pool, janela_s=60, prefixo=prefixo_redis)
    async for chave in redis_pool.scan_iter(match=f"{prefixo_redis}*"):
        await redis_pool.delete(chave)


async def test_bloqueia_ao_atingir_o_maximo_com_ttl_da_janela(
    limite: LimiteTentativasRedis,
) -> None:
    assert await limite.bloqueado([EMAIL, IP]) is None
    for _ in range(2):
        await limite.registrar_falha([EMAIL, IP])
    assert await limite.bloqueado([EMAIL, IP]) is None
    await limite.registrar_falha([EMAIL, IP])
    restante = await limite.bloqueado([EMAIL, IP])
    assert restante is not None and 0 < restante <= 60
    assert await limite.bloqueado([IP]) is None  # o IP ainda tem folga


async def test_limpar_zera_so_as_chaves_dadas(limite: LimiteTentativasRedis) -> None:
    for _ in range(3):
        await limite.registrar_falha([EMAIL, IP])
    await limite.limpar([EMAIL])
    assert await limite.bloqueado([EMAIL]) is None
    await limite.registrar_falha([EMAIL])
    assert await limite.bloqueado([EMAIL]) is None  # recomecou do zero


async def test_janela_expira(redis_pool: ArqRedis, prefixo_redis: str) -> None:
    lim = LimiteTentativasRedis(redis_pool, janela_s=1, prefixo=prefixo_redis)
    try:
        for _ in range(3):
            await lim.registrar_falha([EMAIL])
        assert await lim.bloqueado([EMAIL]) is not None
        await asyncio.sleep(1.3)
        assert await lim.bloqueado([EMAIL]) is None
    finally:
        async for chave in redis_pool.scan_iter(match=f"{prefixo_redis}*"):
            await redis_pool.delete(chave)
