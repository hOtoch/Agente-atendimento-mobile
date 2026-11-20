"""Registro de ids enviados (anti-eco) no Redis real, com prefixo proprio por teste."""

from __future__ import annotations

import asyncio
from uuid import UUID, uuid4

import pytest
from arq.connections import ArqRedis
from redis.asyncio import Redis

from app.adapters.outbound.canal.enviadas import RegistroEnviadasRedis

pytestmark = pytest.mark.integration

LOJA = UUID(int=3)


async def test_registrar_e_consultar(redis_pool: ArqRedis, prefixo_redis: str) -> None:
    registro = RegistroEnviadasRedis(redis_pool, prefixo=prefixo_redis)  # type: ignore[arg-type]
    id_whatsapp = uuid4().hex
    assert await registro.foi_enviada(LOJA, id_whatsapp) is False
    await registro.registrar(LOJA, id_whatsapp)
    assert await registro.foi_enviada(LOJA, id_whatsapp) is True
    assert await registro.foi_enviada(UUID(int=4), id_whatsapp) is False


async def test_o_registro_expira(redis_pool: ArqRedis, prefixo_redis: str) -> None:
    redis: Redis = redis_pool  # type: ignore[assignment]
    registro = RegistroEnviadasRedis(redis, prefixo=prefixo_redis, ttl_s=1)
    await registro.registrar(LOJA, "efemero")
    assert await registro.foi_enviada(LOJA, "efemero") is True
    await asyncio.sleep(1.2)
    assert await registro.foi_enviada(LOJA, "efemero") is False
