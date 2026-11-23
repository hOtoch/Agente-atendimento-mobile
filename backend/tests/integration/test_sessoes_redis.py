"""SessoesRedis contra Redis real, com prefixo proprio por teste (nada vaza para o DB de dev)."""

import asyncio
import hashlib
from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
from arq.connections import ArqRedis

from app.adapters.outbound.auth.sessoes import SessoesRedis

pytestmark = pytest.mark.integration


@pytest.fixture
async def sessoes(redis_pool: ArqRedis, prefixo_redis: str) -> AsyncIterator[SessoesRedis]:
    yield SessoesRedis(redis_pool, ttl_s=60, prefixo=prefixo_redis)
    async for chave in redis_pool.scan_iter(match=f"{prefixo_redis}*"):
        await redis_pool.delete(chave)


async def test_criar_e_obter(sessoes: SessoesRedis) -> None:
    u, loja = uuid4(), uuid4()
    token = await sessoes.criar(u, loja)
    assert len(token) >= 43
    dados = await sessoes.obter(token)
    assert dados is not None and (dados.usuario_id, dados.loja_id) == (u, loja)
    assert await sessoes.obter("outro-token") is None


async def test_redis_nunca_guarda_o_token_em_texto(
    sessoes: SessoesRedis, redis_pool: ArqRedis, prefixo_redis: str
) -> None:
    token = await sessoes.criar(uuid4(), uuid4())
    chaves = [c.decode() async for c in redis_pool.scan_iter(match=f"{prefixo_redis}*")]
    assert chaves
    assert all(token not in c for c in chaves)
    assert any(hashlib.sha256(token.encode()).hexdigest() in c for c in chaves)
    for c in chaves:
        tipo = (await redis_pool.type(c)).decode()
        if tipo == "string":
            valores = [await redis_pool.get(c)]
        else:
            valores = list(await redis_pool.smembers(c))
        assert all(token.encode() not in v for v in valores)


async def test_tokens_sao_unicos(sessoes: SessoesRedis) -> None:
    u, loja = uuid4(), uuid4()
    assert len({await sessoes.criar(u, loja) for _ in range(5)}) == 5


async def test_ttl_e_renovado_a_cada_uso(
    sessoes: SessoesRedis, redis_pool: ArqRedis, prefixo_redis: str
) -> None:
    token = await sessoes.criar(uuid4(), uuid4())
    chave = f"{prefixo_redis}sessao:{hashlib.sha256(token.encode()).hexdigest()}"
    assert 0 < await redis_pool.ttl(chave) <= 60
    await redis_pool.expire(chave, 5)
    assert await sessoes.renovar(token) is True
    assert await redis_pool.ttl(chave) > 5


async def test_sessao_expira_apos_o_ttl(redis_pool: ArqRedis, prefixo_redis: str) -> None:
    curtas = SessoesRedis(redis_pool, ttl_s=1, prefixo=prefixo_redis)
    token = await curtas.criar(uuid4(), uuid4())
    await asyncio.sleep(1.5)
    assert await curtas.obter(token) is None
    assert await curtas.renovar(token) is False


async def test_encerrar(sessoes: SessoesRedis) -> None:
    token = await sessoes.criar(uuid4(), uuid4())
    await sessoes.encerrar(token)
    assert await sessoes.obter(token) is None
    await sessoes.encerrar(token)  # idempotente


async def test_encerrar_do_usuario_mantem_so_a_indicada(sessoes: SessoesRedis) -> None:
    u, loja = uuid4(), uuid4()
    a, b = await sessoes.criar(u, loja), await sessoes.criar(u, loja)
    de_outro = await sessoes.criar(uuid4(), loja)
    await sessoes.encerrar_do_usuario(u, manter=a)
    assert await sessoes.obter(a) is not None
    assert await sessoes.obter(b) is None
    assert await sessoes.obter(de_outro) is not None
    await sessoes.encerrar_do_usuario(u)
    assert await sessoes.obter(a) is None
