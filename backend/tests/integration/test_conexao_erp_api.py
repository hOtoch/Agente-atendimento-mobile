"""API da conexao da loja com o ERP, com o app real e um banco de teste isolado."""

from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.infra.dependencias import get_session
from app.main import app
from tests.integration.conftest import aplicar_migrations
from tests.integration.lojas import criar_loja_no_banco

pytestmark = pytest.mark.integration

CORPO: dict[str, Any] = {
    "system_unit_id": 12,
    "filtro_loja": "Centro",
    "ativo": True,
    "intervalo_min": 30,
    "exportar_handoff": True,
}


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
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        yield c
    app.dependency_overrides.clear()
    await engine.dispose()


async def _loja(client: httpx.AsyncClient) -> str:
    return await criar_loja_no_banco("Loja")


async def test_loja_sem_conexao_responde_config_vazia_e_nao_404(client: httpx.AsyncClient) -> None:
    loja = await _loja(client)
    r = await client.get(f"/lojas/{loja}/config/erp")
    assert r.status_code == 200
    assert r.json() == {
        "configurada": False,
        "provedor": "mercadophone",
        "system_unit_id": None,
        "filtro_loja": None,
        "ativo": False,
        "intervalo_min": 15,
        "exportar_handoff": False,
        "ultima_sincronizacao_em": None,
        "ultimo_status": None,
        "ultimo_relatorio": None,
    }


async def test_salva_e_le_de_volta_e_regrava(client: httpx.AsyncClient) -> None:
    loja = await _loja(client)
    r = await client.put(f"/lojas/{loja}/config/erp", json=CORPO)
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["configurada"] is True
    assert {k: corpo[k] for k in CORPO} == CORPO
    assert (await client.get(f"/lojas/{loja}/config/erp")).json() == corpo
    r2 = await client.put(
        f"/lojas/{loja}/config/erp", json={**CORPO, "ativo": False, "filtro_loja": None}
    )
    assert r2.status_code == 200
    atual = (await client.get(f"/lojas/{loja}/config/erp")).json()
    assert (atual["ativo"], atual["filtro_loja"]) == (False, None)


@pytest.mark.parametrize(
    ("campo", "valor"),
    [("system_unit_id", 0), ("intervalo_min", 4), ("intervalo_min", 1441)],
)
async def test_recusa_valores_invalidos_com_erro_por_campo(
    client: httpx.AsyncClient, campo: str, valor: int
) -> None:
    loja = await _loja(client)
    r = await client.put(f"/lojas/{loja}/config/erp", json={**CORPO, campo: valor})
    assert r.status_code == 422
    assert r.json()["erros"][0]["caminho"] == campo
    assert (await client.get(f"/lojas/{loja}/config/erp")).json()["configurada"] is False


@pytest.mark.parametrize("campo", ["api_key", "chave", "token", "authorization"])
async def test_a_chave_nunca_e_aceita_nem_devolvida(client: httpx.AsyncClient, campo: str) -> None:
    loja = await _loja(client)
    r = await client.put(f"/lojas/{loja}/config/erp", json={**CORPO, campo: "segredo-123"})
    assert r.status_code == 422
    assert "segredo-123" not in r.text
    assert (await client.get(f"/lojas/{loja}/config/erp")).json()["configurada"] is False


async def test_status_da_sincronizacao_e_somente_leitura(client: httpx.AsyncClient) -> None:
    loja = await _loja(client)
    r = await client.put(f"/lojas/{loja}/config/erp", json={**CORPO, "ultimo_status": "ok"})
    assert r.status_code == 422


async def test_loja_inexistente_da_404(client: httpx.AsyncClient) -> None:
    assert (await client.get(f"/lojas/{uuid4()}/config/erp")).status_code == 404
    assert (await client.put(f"/lojas/{uuid4()}/config/erp", json=CORPO)).status_code == 404
