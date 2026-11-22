"""Formas de pagamento e chave Pix no Postgres e na API (migration 0008, repositorio, rotas)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

import httpx
import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.adapters.outbound.db.config import RepositorioConfigLojaSql, RepositorioLojasSql
from app.adapters.outbound.db.models import Base
from app.application.config.modelos import ConfigPagamento
from app.domain.chave_pix import ChavePix, TipoChavePix
from app.infra.dependencias import get_session
from app.main import app
from tests.integration.conftest import aplicar_migrations

pytestmark = pytest.mark.integration

CHAVE = ChavePix(TipoChavePix.EMAIL, "pix@lojademo.exemplo", "Loja Demo")


async def _loja(session: AsyncSession) -> UUID:
    loja_id = await RepositorioLojasSql(session).criar("Loja X")
    await session.commit()
    return loja_id


async def test_migration_0008_sobe_e_desce(db_url: str) -> None:
    engine = create_async_engine(db_url)
    try:
        await aplicar_migrations(db_url, "0007")
        async with engine.connect() as conn:
            antes = await conn.run_sync(lambda c: set(inspect(c).get_table_names()))
        assert "pagamento_loja" not in antes

        await aplicar_migrations(db_url, "head")
        async with engine.connect() as conn:
            depois = await conn.run_sync(lambda c: set(inspect(c).get_table_names()))
            diffs = await conn.run_sync(
                lambda c: compare_metadata(MigrationContext.configure(c), Base.metadata)
            )
        assert "pagamento_loja" in depois
        assert diffs == []

        await aplicar_migrations(db_url, "base")
    finally:
        await engine.dispose()


async def test_pagamento_ida_e_volta_e_upsert(session: AsyncSession) -> None:
    loja = await _loja(session)
    repo = RepositorioConfigLojaSql(session)
    # sem linha: o padrao e Pix, debito e credito, sem chave (como era antes da 0008)
    assert await repo.obter_config_pagamento(loja) == ConfigPagamento(True, True, True, None)

    config = ConfigPagamento(True, False, True, CHAVE)
    await repo.salvar_config_pagamento(loja, config)
    session.expire_all()
    assert await repo.obter_config_pagamento(loja) == config

    sem_chave = ConfigPagamento(False, True, False, None)
    await repo.salvar_config_pagamento(loja, sem_chave)
    session.expire_all()
    assert await repo.obter_config_pagamento(loja) == sem_chave


# --- API ----------------------------------------------------------------------------------


@pytest.fixture
async def client(db_url: str) -> AsyncIterator[httpx.AsyncClient]:
    await aplicar_migrations(db_url)
    engine = create_async_engine(db_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def _sessao() -> AsyncIterator[AsyncSession]:
        async with factory() as s:
            try:
                yield s
            except BaseException:
                await s.rollback()
                raise

    app.dependency_overrides[get_session] = _sessao
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        yield c
    app.dependency_overrides.clear()
    await engine.dispose()


async def _criar_loja(client: httpx.AsyncClient) -> str:
    r = await client.post("/lojas", json={"nome": "Loja API"})
    assert r.status_code == 201
    return str(r.json()["id"])


PAGAMENTO: dict[str, Any] = {
    "aceita_pix": True,
    "aceita_debito": False,
    "aceita_credito": True,
    "chave_pix_tipo": "cnpj",
    "chave_pix": "11.222.333/0001-81",
    "chave_pix_favorecido": "Loja Demo LTDA",
}


async def test_pagamento_padrao_antes_de_configurar(client: httpx.AsyncClient) -> None:
    loja = await _criar_loja(client)
    r = await client.get(f"/lojas/{loja}/config/pagamento")
    assert r.status_code == 200
    assert r.json() == {
        "aceita_pix": True,
        "aceita_debito": True,
        "aceita_credito": True,
        "aceita_entrada_mais_credito": False,
        "chave_pix_tipo": None,
        "chave_pix": None,
        "chave_pix_favorecido": None,
    }


async def test_pagamento_put_e_get_normaliza_a_chave(client: httpx.AsyncClient) -> None:
    loja = await _criar_loja(client)
    r = await client.put(f"/lojas/{loja}/config/pagamento", json=PAGAMENTO)
    assert r.status_code == 200
    esperado = {**PAGAMENTO, "chave_pix": "11222333000181", "aceita_entrada_mais_credito": False}
    assert r.json() == esperado
    assert (await client.get(f"/lojas/{loja}/config/pagamento")).json() == esperado


async def test_entrada_mais_credito_acompanha_as_regras_de_preco(
    client: httpx.AsyncClient,
) -> None:
    loja = await _criar_loja(client)
    preco = {
        "max_parcelas": 12,
        "repassa_taxa": True,
        "desconto_pix_tipo": "nenhum",
        "aceita_entrada_mais_cartao": True,
        "desconto_teto": "0",
        "desconto_degrau": "50",
        "oportunidade_ativa": False,
        "oportunidade_dias_minimos": 0,
        "oportunidade_valor": "0",
    }
    assert (await client.put(f"/lojas/{loja}/config/preco", json=preco)).status_code == 200
    r = await client.get(f"/lojas/{loja}/config/pagamento")
    assert r.json()["aceita_entrada_mais_credito"] is True


async def test_pagamento_chave_invalida_422_com_caminho_do_campo(
    client: httpx.AsyncClient,
) -> None:
    loja = await _criar_loja(client)
    r = await client.put(
        f"/lojas/{loja}/config/pagamento",
        json={**PAGAMENTO, "chave_pix_tipo": "cpf", "chave_pix": "123.456.789-00"},
    )
    assert r.status_code == 422
    assert [e["caminho"] for e in r.json()["erros"]] == ["chave_pix"]
    # nada gravado
    assert (await client.get(f"/lojas/{loja}/config/pagamento")).json()["chave_pix"] is None


async def test_pagamento_loja_inexistente_404(client: httpx.AsyncClient) -> None:
    r = await client.get("/lojas/00000000-0000-0000-0000-000000000001/config/pagamento")
    assert r.status_code == 404


async def test_checklist_acusa_pix_sem_chave_e_some_ao_cadastrar(
    client: httpx.AsyncClient,
) -> None:
    loja = await _criar_loja(client)

    async def item() -> dict[str, Any]:
        itens = (await client.get(f"/lojas/{loja}/onboarding/checklist")).json()["itens"]
        return next(i for i in itens if i["chave"] == "pagamento")

    assert (await item())["completo"] is False
    await client.put(f"/lojas/{loja}/config/pagamento", json=PAGAMENTO)
    assert (await item())["completo"] is True
