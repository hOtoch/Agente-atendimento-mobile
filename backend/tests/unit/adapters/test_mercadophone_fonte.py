"""Adaptador `FonteEstoqueMercadoPhone`: pagina o inventario, resolve marcas e mapeia por loja.

Servidor MCP falso em memoria (`tests/mercadophone_falso.py`) com paginas SINTETICAS.
"""

from __future__ import annotations

from uuid import uuid4

import httpx
import pytest

from app.adapters.outbound.mercadophone.cliente import (
    ClienteMercadoPhone,
    MercadoPhoneIndisponivel,
    MercadoPhoneUsoIndevido,
)
from app.adapters.outbound.mercadophone.fonte import FonteEstoqueMercadoPhone
from app.application.estoque import EstoqueIndisponivel
from app.application.estoque_erp import FonteEstoqueErp
from app.application.relogio import RelogioFalso
from app.domain.conexao_erp import ConexaoErp
from app.domain.oferta import MotivoDescarte
from tests.mercadophone_falso import CHAVE, URL, McpFalso, item


def montar(mcp: McpFalso) -> FonteEstoqueMercadoPhone:
    cliente = ClienteMercadoPhone(mcp.cliente_http(), URL, CHAVE, relogio=RelogioFalso())
    return FonteEstoqueMercadoPhone(cliente)


def conexao(unidade: int = 4, filtro: str | None = None) -> ConexaoErp:
    return ConexaoErp(loja_id=uuid4(), system_unit_id=unidade, filtro_loja=filtro)


def inventario(n: int, *, obs: str = "Loja A", base: int = 1) -> list[dict]:  # type: ignore[type-arg]
    return [item(base + i, obs=obs) for i in range(n)]


def test_implementa_a_porta() -> None:
    fonte: FonteEstoqueErp = montar(McpFalso({}))
    assert fonte is not None


async def test_le_todas_as_paginas_de_300_e_mapeia_para_o_estoque_local() -> None:
    mcp = McpFalso({4: inventario(650)})
    leitura = await montar(mcp).ler(conexao())

    assert (leitura.lidos, len(leitura.linhas), leitura.outra_loja) == (650, 650, 0)
    assert mcp.paginas_lidas(4) == [1, 2, 3]
    primeira = leitura.linhas[0]
    assert primeira.sku == "TESTE-00001"
    assert primeira.erp_produto_id == 1
    assert (primeira.modelo.nome, primeira.modelo.marca) == ("iPhone 15 Pro", "Apple")


async def test_resolve_as_marcas_uma_vez_por_leitura() -> None:
    mcp = McpFalso({4: inventario(650)})
    await montar(mcp).ler(conexao())
    assert [n for n, _ in mcp.chamadas].count("list_brands") == 1


async def test_pede_o_inventario_da_unidade_da_conexao() -> None:
    mcp = McpFalso({4: inventario(2), 7: inventario(5, base=100)})
    leitura = await montar(mcp).ler(conexao(7))
    assert leitura.lidos == 5
    assert {a["store_id"] for n, a in mcp.chamadas if n == "list_inventory"} == {7}


async def test_filtro_de_loja_separa_as_lojas_que_dividem_a_unidade() -> None:
    itens = [*inventario(3, obs="Loja A | vitrine"), *inventario(2, obs="Loja B", base=100)]
    fonte = montar(McpFalso({4: itens}))

    unidade = await fonte.ler_unidade(4)
    a = unidade.para_loja("Loja A")
    b = unidade.para_loja("Loja B")
    todas = unidade.para_loja(None)

    assert (len(a.linhas), a.outra_loja, a.lidos) == (3, 2, 5)
    assert (len(b.linhas), b.outra_loja, b.lidos) == (2, 3, 5)
    assert (len(todas.linhas), todas.outra_loja) == (5, 0)


async def test_ler_unidade_nao_repete_a_leitura_ao_aplicar_varios_filtros() -> None:
    mcp = McpFalso({4: [*inventario(3, obs="Loja A"), *inventario(2, obs="Loja B", base=100)]})
    unidade = await montar(mcp).ler_unidade(4)
    unidade.para_loja("Loja A")
    unidade.para_loja("Loja B")
    assert mcp.leituras_do_inventario() == 1


async def test_relatorio_traz_os_descartes_por_motivo() -> None:
    itens = [
        item(1),
        item(2, preco=0.01),
        item(3, quantidade=0),
        item(4, tipo="Acessório"),
        item(5, estado="DEFEITO"),
    ]
    leitura = await montar(McpFalso({4: itens})).ler(conexao())
    assert len(leitura.linhas) == 1
    assert leitura.descartes == {
        MotivoDescarte.SEM_PRECO: 1,
        MotivoDescarte.SEM_QUANTIDADE: 1,
        MotivoDescarte.NAO_E_CELULAR: 1,
        MotivoDescarte.ESTADO_NAO_INFORMADO: 1,
    }


async def test_falha_na_pagina_n_levanta_e_nao_devolve_leitura_parcial() -> None:
    mcp = McpFalso({4: inventario(650)}, falha_na_pagina={2: httpx.Response(503)})
    with pytest.raises(MercadoPhoneIndisponivel):
        await montar(mcp).ler(conexao())
    assert mcp.paginas_lidas(4) == [1, 2]  # parou na falha


async def test_o_erro_da_fonte_e_estoque_indisponivel() -> None:
    mcp = McpFalso({4: inventario(10)}, falha_na_pagina={1: httpx.Response(503)})
    with pytest.raises(EstoqueIndisponivel):
        await montar(mcp).ler_unidade(4)


async def test_marcas_que_exigem_a_loja_sao_pedidas_com_store_id() -> None:
    mcp = McpFalso({4: inventario(2)}, marcas_exigem_loja=True)
    leitura = await montar(mcp).ler(conexao())
    assert len(leitura.linhas) == 2
    chamadas_marcas = [a for n, a in mcp.chamadas if n == "list_brands"]
    assert "store_id" not in chamadas_marcas[0]
    assert chamadas_marcas[-1]["store_id"] == 4


async def test_outro_erro_de_uso_nas_marcas_nao_e_engolido() -> None:
    mcp = McpFalso({4: inventario(2)})
    erro = {"error": "x", "status": 422, "code": "validation_error"}
    mcp._payload = lambda nome, args: erro if nome == "list_brands" else {}  # type: ignore[method-assign]
    with pytest.raises(MercadoPhoneUsoIndevido):
        await montar(mcp).ler_unidade(4)


async def test_unidade_existe_consulta_as_lojas_da_chave() -> None:
    mcp = McpFalso({}, lojas_da_chave=[4, 9])
    fonte = montar(mcp)
    assert await fonte.unidade_existe(4) is True
    assert await fonte.unidade_existe(5) is False
    assert mcp.chamadas[0][0] == "list_my_stores"
