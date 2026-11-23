"""RepositorioUsuariosSql e a migration 0009 contra Postgres real."""

from datetime import UTC, datetime

import pytest
from alembic import command
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.adapters.outbound.auth.usuarios import RepositorioUsuariosSql
from app.adapters.outbound.db.config import RepositorioLojasSql
from tests.integration.conftest import alembic_config

pytestmark = pytest.mark.integration


async def test_criar_e_obter_normaliza_email(session: AsyncSession) -> None:
    loja = await RepositorioLojasSql(session).criar("Loja X")
    repo = RepositorioUsuariosSql(session)
    criado = await repo.criar(loja, "  Dono@Loja.COM ", "hash-x", senha_provisoria=True)
    assert criado.email == "dono@loja.com" and criado.loja_nome == "Loja X"
    por_email = await repo.obter_por_email("DONO@loja.com")
    assert por_email is not None and por_email.id == criado.id
    assert por_email.senha_hash == "hash-x" and por_email.ativo and por_email.senha_provisoria
    assert (await repo.obter_por_id(criado.id)) == por_email
    assert await repo.obter_por_email("outro@loja.com") is None


async def test_email_e_unico(session: AsyncSession) -> None:
    loja = await RepositorioLojasSql(session).criar("Loja X")
    repo = RepositorioUsuariosSql(session)
    await repo.criar(loja, "a@a.com", "h", senha_provisoria=False)
    with pytest.raises(IntegrityError):
        await repo.criar(loja, "A@a.com", "h", senha_provisoria=False)


async def test_atualizar_senha_e_registrar_login(session: AsyncSession) -> None:
    loja = await RepositorioLojasSql(session).criar("Loja X")
    repo = RepositorioUsuariosSql(session)
    u = await repo.criar(loja, "a@a.com", "h1", senha_provisoria=True)
    assert u.ultimo_login_em is None
    await repo.atualizar_senha(u.id, "h2", senha_provisoria=False)
    await repo.registrar_login(u.id, datetime(2026, 1, 1, tzinfo=UTC))
    novo = await repo.obter_por_id(u.id)
    assert novo is not None
    assert (novo.senha_hash, novo.senha_provisoria) == ("h2", False)
    assert novo.ultimo_login_em == datetime(2026, 1, 1, tzinfo=UTC)


async def test_apagar_a_loja_apaga_o_usuario(session: AsyncSession) -> None:
    loja = await RepositorioLojasSql(session).criar("Loja X")
    repo = RepositorioUsuariosSql(session)
    u = await repo.criar(loja, "a@a.com", "h", senha_provisoria=False)
    await session.execute(text("DELETE FROM lojas WHERE id = :i"), {"i": loja})
    assert await repo.obter_por_id(u.id) is None


async def test_loja_aceita_mais_de_um_usuario(session: AsyncSession) -> None:
    loja = await RepositorioLojasSql(session).criar("Loja X")
    repo = RepositorioUsuariosSql(session)
    await repo.criar(loja, "a@a.com", "h", senha_provisoria=False)
    await repo.criar(loja, "b@a.com", "h", senha_provisoria=False)


async def test_migration_0009_sobe_e_desce(db_url: str) -> None:
    engine = create_async_engine(db_url)
    try:
        async with engine.connect() as conn:

            def _rodar(sync_conn) -> None:  # type: ignore[no-untyped-def]
                cfg = alembic_config(db_url)
                cfg.attributes["connection"] = sync_conn
                command.upgrade(cfg, "head")
                existe = "SELECT to_regclass('public.usuarios') IS NOT NULL"
                assert sync_conn.exec_driver_sql(existe).scalar() is True
                command.downgrade(cfg, "0008")
                assert sync_conn.exec_driver_sql(existe).scalar() is False
                command.upgrade(cfg, "head")

            await conn.run_sync(_rodar)
            await conn.commit()
    finally:
        await engine.dispose()
