"""Fixtures de integracao: um banco Postgres ISOLADO por teste, com as migrations aplicadas."""

import os
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import asyncpg
import pytest
from alembic import command
from alembic.config import Config
from arq.connections import ArqRedis, RedisSettings, create_pool
from redis.exceptions import RedisError
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError, InterfaceError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.infra.settings import get_settings

BACKEND_DIR = Path(__file__).resolve().parents[2]

_ERROS_DE_CONEXAO = (
    OSError,
    TimeoutError,
    asyncpg.PostgresError,
    asyncpg.InterfaceError,
    OperationalError,
    InterfaceError,
    DBAPIError,
)


def alembic_config(database_url: str) -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    cfg.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return cfg


async def aplicar_migrations(database_url: str, revisao: str = "head") -> None:
    """Roda `alembic upgrade` (ou downgrade, se `revisao` for `base`) numa conexao async."""
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as conn:

            def _rodar(sync_conn) -> None:  # type: ignore[no-untyped-def]
                cfg = alembic_config(database_url)
                cfg.attributes["connection"] = sync_conn
                if revisao == "base":
                    command.downgrade(cfg, "base")
                else:
                    command.upgrade(cfg, revisao)

            await conn.run_sync(_rodar)
            await conn.commit()
    finally:
        await engine.dispose()


@pytest.fixture
async def db_url() -> AsyncIterator[str]:
    """Cria `teste_<id>` no Postgres de teste e dropa no final.

    Servidor fora: pula; ou falha se `EXIGIR_INTEGRACAO=1` (CI), para nao ficar verde sem testar.
    """
    admin_url = make_url(get_settings().test_database_url)
    admin = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    nome = f"teste_{uuid.uuid4().hex[:8]}"
    try:
        async with admin.connect() as conn:
            await conn.execute(text(f'CREATE DATABASE "{nome}"'))
    except _ERROS_DE_CONEXAO as exc:
        await admin.dispose()
        msg = f"Postgres de teste inacessivel em {admin_url.host}:{admin_url.port}: {exc!r}"
        if os.environ.get("EXIGIR_INTEGRACAO") == "1":
            pytest.fail(f"EXIGIR_INTEGRACAO=1 e o {msg}", pytrace=False)
        pytest.skip(msg)
    try:
        yield admin_url.set(database=nome).render_as_string(hide_password=False)
    finally:
        async with admin.connect() as conn:
            await conn.execute(text(f'DROP DATABASE IF EXISTS "{nome}" WITH (FORCE)'))
        await admin.dispose()


@pytest.fixture
async def session(db_url: str) -> AsyncIterator[AsyncSession]:
    """AsyncSession num banco isolado ja migrado."""
    await aplicar_migrations(db_url)
    engine = create_async_engine(db_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


@pytest.fixture
async def redis_pool() -> AsyncIterator[ArqRedis]:
    """Pool arq/Redis; pula se o Redis estiver fora (falha com `EXIGIR_INTEGRACAO=1`).

    Cada teste usa um prefixo de chave e uma fila proprios (ver `prefixo_redis`), entao nada
    precisa ser limpo entre testes nem colide com o Redis de desenvolvimento.
    """
    url = get_settings().redis_url
    try:
        pool = await create_pool(RedisSettings.from_dsn(url), retry=0)
        await pool.ping()
    except (OSError, TimeoutError, RedisError) as exc:
        msg = f"Redis inacessivel em {url}: {exc!r}"
        if os.environ.get("EXIGIR_INTEGRACAO") == "1":
            pytest.fail(f"EXIGIR_INTEGRACAO=1 e o {msg}", pytrace=False)
        pytest.skip(msg)
    try:
        yield pool
    finally:
        await pool.aclose()


@pytest.fixture
def prefixo_redis() -> str:
    return f"teste:{uuid.uuid4().hex[:8]}:"
