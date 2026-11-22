"""POST /lojas/{id}/vendedores/importar-erp com o app real, banco isolado e leitor falso."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.adapters.outbound.mercadophone.cliente import (
    MercadoPhoneCredencialInvalida,
    MercadoPhoneIndisponivel,
)
from app.application.config.vendedores_erp import VendedorErp
from app.infra import dependencias
from app.infra.dependencias import get_leitor_vendedores_erp, get_session
from app.infra.mercadophone import MercadoPhoneNaoConfigurado
from app.main import app
from tests.integration.conftest import aplicar_migrations

pytestmark = pytest.mark.integration


class LeitorFalso:
    def __init__(self) -> None:
        self.itens: list[VendedorErp] = []
        self.erro: Exception | None = None

    async def listar(self, system_unit_id: int) -> list[VendedorErp]:
        if self.erro is not None:
            raise self.erro
        return list(self.itens)


@pytest.fixture
async def ctx(db_url: str) -> AsyncIterator[tuple[httpx.AsyncClient, LeitorFalso]]:
    await aplicar_migrations(db_url)
    engine = create_async_engine(db_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    leitor = LeitorFalso()

    async def _sessao() -> AsyncIterator[AsyncSession]:
        async with factory() as s:
            try:
                yield s
            except BaseException:
                await s.rollback()
                raise

    app.dependency_overrides[get_session] = _sessao
    app.dependency_overrides[get_leitor_vendedores_erp] = lambda: leitor
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        yield c, leitor
    app.dependency_overrides.clear()
    await engine.dispose()


async def _loja(client: httpx.AsyncClient, *, conectar: bool = True) -> str:
    loja = str((await client.post("/lojas", json={"nome": "Loja"})).json()["id"])
    if conectar:
        r = await client.put(f"/lojas/{loja}/config/erp", json={"system_unit_id": 12})
        assert r.status_code == 200, r.text
    return loja


def _url(loja: str) -> str:
    return f"/lojas/{loja}/vendedores/importar-erp"


async def test_importa_devolve_resumo_e_os_vendedores_aparecem_com_codigo_erp(ctx: Any) -> None:
    client, leitor = ctx
    loja = await _loja(client)
    leitor.itens = [VendedorErp("9", "Fulano", True), VendedorErp("10", "Beltrana", True)]

    r = await client.post(_url(loja))

    assert r.status_code == 200, r.text
    assert r.json() == {"criados": 2, "atualizados": 0, "desativados": 0, "sem_alteracao": 0}
    lista = (await client.get(f"/lojas/{loja}/config/vendedores")).json()["vendedores"]
    assert [(v["nome"], v["codigo_erp"], float(v["peso_percentual"])) for v in lista] == [
        ("Fulano", "9", 0.0),
        ("Beltrana", "10", 0.0),
    ]


async def test_reimportar_nao_duplica(ctx: Any) -> None:
    client, leitor = ctx
    loja = await _loja(client)
    leitor.itens = [VendedorErp("9", "Fulano", True)]
    await client.post(_url(loja))

    r = await client.post(_url(loja))

    assert r.json() == {"criados": 0, "atualizados": 0, "desativados": 0, "sem_alteracao": 1}
    assert len((await client.get(f"/lojas/{loja}/config/vendedores")).json()["vendedores"]) == 1


async def test_vendedor_criado_a_mao_tem_codigo_erp_nulo(ctx: Any) -> None:
    client, _ = ctx
    loja = await _loja(client)
    await client.put(
        f"/lojas/{loja}/config/vendedores",
        json={"vendedores": [{"nome": "Ana", "peso_percentual": 100}]},
    )
    (v,) = (await client.get(f"/lojas/{loja}/config/vendedores")).json()["vendedores"]
    assert v["codigo_erp"] is None


async def test_loja_inexistente_404(ctx: Any) -> None:
    client, _ = ctx
    r = await client.post(_url(str(uuid4())))
    assert r.status_code == 404


async def test_loja_sem_conexao_409(ctx: Any) -> None:
    client, _ = ctx
    loja = await _loja(client, conectar=False)
    r = await client.post(_url(loja))
    assert r.status_code == 409
    assert r.json()["erros"][0]["mensagem"] == "Loja sem conexão com o ERP."


async def test_erp_fora_503(ctx: Any) -> None:
    client, leitor = ctx
    loja = await _loja(client)
    leitor.erro = MercadoPhoneIndisponivel("timeout")
    r = await client.post(_url(loja))
    assert r.status_code == 503
    assert "indisponível" in r.json()["erros"][0]["mensagem"]


async def test_credencial_invalida_502_sem_vazar_a_chave(ctx: Any) -> None:
    client, leitor = ctx
    loja = await _loja(client)
    leitor.erro = MercadoPhoneCredencialInvalida("recusou segredo-abc", codigo="invalid_key")
    r = await client.post(_url(loja))
    assert r.status_code == 502
    assert "segredo-abc" not in r.text


async def test_sem_chave_no_servidor_409(ctx: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    client, _ = ctx
    loja = await _loja(client)

    def _sem_chave() -> None:
        raise MercadoPhoneNaoConfigurado("MERCADOPHONE_API_KEY nao configurada")

    monkeypatch.setattr(dependencias, "get_cliente_mercadophone", _sem_chave)
    app.dependency_overrides.pop(get_leitor_vendedores_erp)

    r = await client.post(_url(loja))

    assert r.status_code == 409
    assert r.json()["erros"][0]["mensagem"] == "Integração com o ERP não configurada no servidor."
