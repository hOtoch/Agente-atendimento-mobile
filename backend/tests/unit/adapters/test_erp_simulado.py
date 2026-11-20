"""Casos especificos do ErpSimuladoAdapter (paginacao, mapeamento, erros HTTP)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from decimal import Decimal
from typing import Any
from uuid import UUID

import httpx
import pytest
import respx

from app.adapters.outbound.estoque.erp_simulado import ErpCredencialInvalida, ErpSimuladoAdapter
from app.adapters.outbound.estoque.memoria import FonteMapeamentoEmMemoria
from app.application.estoque import EstoqueIndisponivel
from app.domain.estoque import Condicao, MapeamentoSku
from app.domain.valores import Capacidade, Dinheiro, ModeloAparelho
from tests.erp_falso import BASE_URL, TOKEN, montar_erp, produto

LOJA = UUID("00000000-0000-0000-0000-0000000000a1")


def mapa(
    sku: str,
    modelo: str = "iPhone 15 Pro",
    cor: str | None = "Preto",
    condicao: Condicao = Condicao.NOVO,
) -> MapeamentoSku:
    return MapeamentoSku(
        sku_externo=sku,
        modelo=ModeloAparelho.de(modelo),
        capacidade=Capacidade(256),
        cor=cor,
        condicao=condicao,
    )


@pytest.fixture
async def router() -> AsyncIterator[respx.MockRouter]:
    with respx.mock(assert_all_called=False) as r:
        yield r


@pytest.fixture
async def cliente() -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient() as c:
        yield c


def adaptador(
    cliente: httpx.AsyncClient, mapeamentos: dict[str, MapeamentoSku], token: str = TOKEN
) -> ErpSimuladoAdapter:
    return ErpSimuladoAdapter(
        cliente, BASE_URL, token, FonteMapeamentoEmMemoria({LOJA: mapeamentos}), timeout_s=1.0
    )


async def test_percorre_todas_as_paginas(
    router: respx.MockRouter, cliente: httpx.AsyncClient
) -> None:
    produtos: list[dict[str, Any]] = [produto(f"S{n:03d}", f"X {n}") for n in range(250)]
    montar_erp(router, produtos)
    a = adaptador(cliente, {p["sku"]: mapa(p["sku"]) for p in produtos})
    achados = await a.buscar(LOJA, "iPhone 15 Pro")
    assert len(achados) == 250
    assert [c.request.url.params["pagina"] for c in router.calls] == ["1", "2", "3"]
    assert all(c.request.url.params["tamanho"] == "100" for c in router.calls)


async def test_envia_bearer_token(router: respx.MockRouter, cliente: httpx.AsyncClient) -> None:
    montar_erp(router, [produto("A", "x")])
    await adaptador(cliente, {"A": mapa("A")}).buscar(LOJA, "iPhone 15 Pro")
    assert router.calls.last.request.headers["authorization"] == f"Bearer {TOKEN}"


async def test_preco_vira_dinheiro_e_quantidade_vem_do_erp(
    router: respx.MockRouter, cliente: httpx.AsyncClient
) -> None:
    montar_erp(router, [produto("A", "x", preco="7499.00", estoque=4)])
    (item,) = await adaptador(cliente, {"A": mapa("A")}).buscar(LOJA, "iPhone 15 Pro")
    assert item.preco_pix == Dinheiro.de(Decimal("7499.00"))
    assert item.quantidade == 4
    assert item.modelo.nome == "iPhone 15 Pro"
    assert item.cor == "Preto"


async def test_bateria_vem_do_marcador_bat_so_para_seminovo(
    router: respx.MockRouter, cliente: httpx.AsyncClient
) -> None:
    montar_erp(router, [produto("SN", "qualquer BAT 88"), produto("NV", "qualquer BAT 99")])
    a = adaptador(
        cliente,
        {"SN": mapa("SN", condicao=Condicao.SEMINOVO), "NV": mapa("NV")},
    )
    semi = await a.obter(LOJA, "SN")
    novo = await a.obter(LOJA, "NV")
    assert semi is not None
    assert semi.bateria_pct == 88
    assert novo is not None
    assert novo.bateria_pct is None


async def test_sku_nao_mapeado_e_ignorado_e_registrado(
    router: respx.MockRouter, cliente: httpx.AsyncClient
) -> None:
    montar_erp(
        router,
        [
            produto("OK", "x"),
            produto("CAPA-1", "CAPA SILICONE P/ IPHONE 15 PRO"),
            produto("MISTERIO", "IPH 15 PRO"),  # parser: confianca baixa (sem capacidade/cor)
        ],
    )
    a = adaptador(cliente, {"OK": mapa("OK")})
    achados = await a.buscar(LOJA, "iPhone 15 Pro")
    assert [i.sku for i in achados] == ["OK"]
    assert sorted(a.skus_nao_mapeados(LOJA)) == ["CAPA-1", "MISTERIO"]
    assert a.skus_nao_mapeados(UUID(int=7)) == []


async def test_sku_sem_mapeamento_usa_parser_com_confianca_alta(
    router: respx.MockRouter, cliente: httpx.AsyncClient
) -> None:
    montar_erp(router, [produto("APL-1", "IPH 15 PRO 256 TIT NAT", "7499.00", 4)])
    a = adaptador(cliente, {})
    (item,) = await a.buscar(LOJA, "iPhone 15 Pro")
    assert item.cor == "Titânio Natural"
    assert item.capacidade == Capacidade(256)
    assert item.condicao is Condicao.NOVO
    assert a.skus_nao_mapeados(LOJA) == []


async def test_obter_sku_nao_mapeado_retorna_none_e_registra(
    router: respx.MockRouter, cliente: httpx.AsyncClient
) -> None:
    montar_erp(router, [produto("CABO", "CABO USB-C")])
    a = adaptador(cliente, {})
    assert await a.obter(LOJA, "CABO") is None
    assert a.skus_nao_mapeados(LOJA) == ["CABO"]


async def test_obter_404_retorna_none(router: respx.MockRouter, cliente: httpx.AsyncClient) -> None:
    montar_erp(router, [])
    assert await adaptador(cliente, {}).obter(LOJA, "NADA") is None


async def test_obter_esgotado_retorna_item(
    router: respx.MockRouter, cliente: httpx.AsyncClient
) -> None:
    montar_erp(router, [produto("A", "x", estoque=0)])
    item = await adaptador(cliente, {"A": mapa("A")}).obter(LOJA, "A")
    assert item is not None
    assert item.quantidade == 0


@pytest.mark.parametrize("status", [500, 502, 503])
async def test_5xx_vira_estoque_indisponivel(
    router: respx.MockRouter, cliente: httpx.AsyncClient, status: int
) -> None:
    router.get(url__regex=rf"{BASE_URL}/produtos.*").mock(return_value=httpx.Response(status))
    a = adaptador(cliente, {})
    with pytest.raises(EstoqueIndisponivel):
        await a.buscar(LOJA, "iPhone 15 Pro")
    with pytest.raises(EstoqueIndisponivel):
        await a.obter(LOJA, "A")


async def test_401_vira_credencial_invalida(
    router: respx.MockRouter, cliente: httpx.AsyncClient
) -> None:
    montar_erp(router, [produto("A", "x")])
    a = adaptador(cliente, {"A": mapa("A")}, token="errado")
    with pytest.raises(ErpCredencialInvalida):
        await a.buscar(LOJA, "iPhone 15 Pro")
    with pytest.raises(ErpCredencialInvalida):
        await a.obter(LOJA, "A")
    assert issubclass(ErpCredencialInvalida, EstoqueIndisponivel)


async def test_timeout_vira_estoque_indisponivel(
    router: respx.MockRouter, cliente: httpx.AsyncClient
) -> None:
    router.get(url__regex=rf"{BASE_URL}/produtos.*").mock(side_effect=httpx.ReadTimeout("lento"))
    with pytest.raises(EstoqueIndisponivel):
        await adaptador(cliente, {}).buscar(LOJA, "iPhone 15 Pro")


async def test_erro_de_rede_vira_estoque_indisponivel(
    router: respx.MockRouter, cliente: httpx.AsyncClient
) -> None:
    router.get(url__regex=rf"{BASE_URL}/produtos.*").mock(side_effect=httpx.ConnectError("fora"))
    with pytest.raises(EstoqueIndisponivel):
        await adaptador(cliente, {}).obter(LOJA, "A")


async def test_resposta_malformada_vira_estoque_indisponivel(
    router: respx.MockRouter, cliente: httpx.AsyncClient
) -> None:
    router.get(url__regex=rf"{BASE_URL}/produtos.*").mock(
        return_value=httpx.Response(200, content=b"<html>nao e json</html>")
    )
    with pytest.raises(EstoqueIndisponivel):
        await adaptador(cliente, {}).buscar(LOJA, "iPhone 15 Pro")


async def test_fonte_de_mapeamento_em_memoria() -> None:
    fonte = FonteMapeamentoEmMemoria({LOJA: {"A": mapa("A")}})
    assert list(await fonte.listar(LOJA)) == ["A"]
    assert await fonte.listar(UUID(int=9)) == {}
