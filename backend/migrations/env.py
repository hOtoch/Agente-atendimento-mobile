import asyncio

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.adapters.outbound.db.models import Base
from app.infra.settings import get_settings

config = context.config
target_metadata = Base.metadata


def _url() -> str:
    return config.get_main_option("sqlalchemy.url") or get_settings().database_url


def _migrar(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def _migrar_async() -> None:
    cfg = {"sqlalchemy.url": _url()}
    engine = async_engine_from_config(cfg, prefix="sqlalchemy.", poolclass=pool.NullPool)
    async with engine.connect() as conn:
        await conn.run_sync(_migrar)
    await engine.dispose()


if context.is_offline_mode():
    context.configure(url=_url(), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    conexao = config.attributes.get("connection")
    if conexao is not None:  # chamado de dentro de uma conexao async (testes)
        _migrar(conexao)
    else:
        asyncio.run(_migrar_async())
