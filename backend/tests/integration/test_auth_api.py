"""Fluxo /auth ponta a ponta: Postgres e Redis reais (sessoes com prefixo proprio)."""

from collections.abc import AsyncIterator
from typing import Annotated

import httpx
import pytest
from arq.connections import ArqRedis
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.adapters.outbound.auth.hasher import HasherSenhaArgon2
from app.adapters.outbound.auth.limite import LimiteTentativasRedis
from app.adapters.outbound.auth.sessoes import SessoesRedis
from app.adapters.outbound.auth.usuarios import RepositorioUsuariosSql
from app.adapters.outbound.db.config import RepositorioLojasSql
from app.application.auth.modelos import SessaoAtual
from app.infra.dependencias import (
    get_limite_tentativas,
    get_session,
    get_sessoes,
    sessao_atual,
)
from app.main import app
from tests.integration.conftest import aplicar_migrations

pytestmark = pytest.mark.integration

SENHA = "senha-provisoria-1"


@pytest.fixture
async def client(
    db_url: str, redis_pool: ArqRedis, prefixo_redis: str
) -> AsyncIterator[httpx.AsyncClient]:
    await aplicar_migrations(db_url)
    engine = create_async_engine(db_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        loja = await RepositorioLojasSql(s).criar("Loja Real")
        await RepositorioUsuariosSql(s).criar(
            loja, "dono@loja.com", await HasherSenhaArgon2().gerar(SENHA), senha_provisoria=True
        )
        await s.commit()
    sessoes = SessoesRedis(redis_pool, ttl_s=60, prefixo=prefixo_redis)

    async def _sessao() -> AsyncIterator[AsyncSession]:
        async with factory() as s:
            yield s

    app.dependency_overrides[get_session] = _sessao
    app.dependency_overrides[get_sessoes] = lambda: sessoes
    limite = LimiteTentativasRedis(redis_pool, janela_s=60, prefixo=prefixo_redis)
    app.dependency_overrides[get_limite_tentativas] = lambda: limite
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        yield c
    app.dependency_overrides.clear()
    async for chave in redis_pool.scan_iter(match=f"{prefixo_redis}*"):
        await redis_pool.delete(chave)
    await engine.dispose()


async def test_fluxo_completo(client: httpx.AsyncClient, db_url: str) -> None:
    r = await client.post("/auth/login", json={"email": "DONO@loja.com", "senha": SENHA})
    assert r.status_code == 200 and "httponly" in r.headers["set-cookie"].lower()
    assert (await client.get("/auth/eu")).json()["loja_nome"] == "Loja Real"

    token_antigo = client.cookies["sessao"]
    r = await client.put(
        "/auth/senha", json={"senha_atual": SENHA, "senha_nova": "outra-senha-forte"}
    )
    assert r.status_code == 204
    assert (await client.get("/auth/eu")).json()["senha_provisoria"] is False

    # o banco nunca guarda a senha em texto
    engine = create_async_engine(db_url)
    async with engine.connect() as conn:
        consulta = "SELECT senha_hash, ultimo_login_em FROM usuarios"
        linhas = (await conn.exec_driver_sql(consulta)).all()
    await engine.dispose()
    assert linhas[0][0].startswith("$argon2id$") and "outra-senha-forte" not in linhas[0][0]
    assert linhas[0][1] is not None

    assert (await client.post("/auth/logout")).status_code == 204
    assert (await client.get("/auth/eu", cookies={"sessao": token_antigo})).status_code == 401


async def test_dependencia_sessao_atual_le_o_cookie(client: httpx.AsyncClient) -> None:
    @app.get("/_teste/sessao")
    async def _rota(s: Annotated[SessaoAtual, Depends(sessao_atual)]) -> dict[str, str]:
        return {"loja_id": str(s.loja_id)}

    try:
        assert (await client.get("/_teste/sessao")).status_code == 401
        await client.post("/auth/login", json={"email": "dono@loja.com", "senha": SENHA})
        r = await client.get("/_teste/sessao")
        assert r.status_code == 200 and r.json()["loja_id"]
    finally:
        app.router.routes[:] = [
            x for x in app.router.routes if getattr(x, "path", "") != "/_teste/sessao"
        ]
