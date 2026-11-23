"""Rotas `testar` e `sincronizar` da conexao com o ERP, com o app real e o MCP falso."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from typing import Any
from uuid import uuid4

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.adapters.outbound.mercadophone.cliente import ClienteMercadoPhone
from app.adapters.outbound.mercadophone.fonte import FonteEstoqueMercadoPhone
from app.application.relogio import RelogioFalso
from app.infra import dependencias
from app.infra.dependencias import get_fonte_estoque_erp, get_session
from app.infra.mercadophone import MercadoPhoneNaoConfigurado
from app.main import app
from tests.integration.conftest import aplicar_migrations
from tests.integration.lojas import criar_loja_no_banco
from tests.mercadophone_falso import CHAVE, URL, McpFalso, item

pytestmark = pytest.mark.integration

CORPO: dict[str, Any] = {
    "system_unit_id": 4,
    "filtro_loja": None,
    "ativo": False,
    "intervalo_min": 15,
    "exportar_handoff": False,
}


@pytest.fixture
def mcp() -> McpFalso:
    return McpFalso({4: [item(i) for i in range(1, 6)]}, lojas_da_chave=[4])


@pytest.fixture
async def client(db_url: str, mcp: McpFalso) -> AsyncIterator[httpx.AsyncClient]:
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

    cliente = ClienteMercadoPhone(mcp.cliente_http(), URL, CHAVE, relogio=RelogioFalso())
    app.dependency_overrides[get_session] = _sessao
    app.dependency_overrides[get_fonte_estoque_erp] = lambda: FonteEstoqueMercadoPhone(cliente)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        yield c
    app.dependency_overrides.clear()
    await engine.dispose()


async def _loja(client: httpx.AsyncClient, *, conexao: dict[str, Any] | None = CORPO) -> str:
    loja = await criar_loja_no_banco("Loja")
    if conexao is not None:
        r = await client.put(f"/lojas/{loja}/config/erp", json=conexao)
        assert r.status_code == 200, r.text
    return loja


async def test_sincronizar_agora_grava_estoque_e_devolve_a_conexao_com_status(
    client: httpx.AsyncClient,
) -> None:
    loja = await _loja(client)  # inativa: a sincronizacao manual funciona mesmo assim
    r = await client.post(f"/lojas/{loja}/config/erp/sincronizar")
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["ultimo_status"] == "ok"
    assert corpo["ultima_sincronizacao_em"] is not None
    rel = corpo["ultimo_relatorio"]
    assert (rel["lidos"], rel["importados"], rel["outra_loja"], rel["descartados"]) == (5, 5, 0, 0)
    assert rel["por_motivo"] == {}
    assert rel["duracao_s"] >= 0
    estoque = (await client.get(f"/lojas/{loja}/config/estoque")).json()
    assert len(estoque["estoque"]) == 5
    assert (await client.get(f"/lojas/{loja}/config/erp")).json() == corpo


async def test_sincronizar_com_erp_fora_responde_200_com_status_erro(
    client: httpx.AsyncClient, mcp: McpFalso
) -> None:
    loja = await _loja(client)
    mcp.falha_na_pagina[1] = httpx.Response(503)
    r = await client.post(f"/lojas/{loja}/config/erp/sincronizar")
    assert r.status_code == 200
    assert r.json()["ultimo_status"] == "erro"
    assert "503" in r.json()["ultimo_relatorio"]["erro"]
    assert CHAVE not in r.text


async def test_sincronizar_sem_conexao_configurada_da_409(client: httpx.AsyncClient) -> None:
    loja = await _loja(client, conexao=None)
    r = await client.post(f"/lojas/{loja}/config/erp/sincronizar")
    assert r.status_code == 409
    assert r.json()["erros"][0]["caminho"] == "conexao"
    assert (await client.post(f"/lojas/{loja}/config/erp/testar")).status_code == 409


async def test_loja_inexistente_da_404(client: httpx.AsyncClient) -> None:
    assert (await client.post(f"/lojas/{uuid4()}/config/erp/sincronizar")).status_code == 404
    assert (await client.post(f"/lojas/{uuid4()}/config/erp/testar")).status_code == 404


async def test_testar_confirma_que_a_unidade_existe_na_chave(client: httpx.AsyncClient) -> None:
    loja = await _loja(client)
    r = await client.post(f"/lojas/{loja}/config/erp/testar")
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert "4" in r.json()["mensagem"]


async def test_testar_unidade_que_nao_existe_na_chave(client: httpx.AsyncClient) -> None:
    loja = await _loja(client, conexao={**CORPO, "system_unit_id": 77})
    r = await client.post(f"/lojas/{loja}/config/erp/testar")
    assert r.status_code == 200
    assert r.json()["ok"] is False
    assert "77" in r.json()["mensagem"]


async def test_testar_nao_mexe_no_estoque_nem_no_status(client: httpx.AsyncClient) -> None:
    loja = await _loja(client)
    await client.post(f"/lojas/{loja}/config/erp/testar")
    assert (await client.get(f"/lojas/{loja}/config/erp")).json()["ultimo_status"] is None
    assert (await client.get(f"/lojas/{loja}/config/estoque")).json()["estoque"] == []


@pytest.fixture
def sem_chave(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    def _levanta() -> None:
        raise MercadoPhoneNaoConfigurado("MERCADOPHONE_API_KEY nao configurada")

    monkeypatch.setattr(dependencias, "get_cliente_mercadophone", _levanta)
    yield


@pytest.mark.usefixtures("sem_chave")
async def test_sem_chave_no_servidor_as_rotas_respondem_409_claro(
    client: httpx.AsyncClient,
) -> None:
    app.dependency_overrides.pop(get_fonte_estoque_erp, None)
    loja = await _loja(client)
    for rota in ("testar", "sincronizar"):
        r = await client.post(f"/lojas/{loja}/config/erp/{rota}")
        assert r.status_code == 409, r.text
        erro = r.json()["erros"][0]
        assert erro["caminho"] == "erp"
        assert erro["mensagem"] == "Integração com o ERP não configurada no servidor."
