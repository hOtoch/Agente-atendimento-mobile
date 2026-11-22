"""`ConferenciaItemMercadoPhone`: 1 chamada `list_inventory(sku=...)` e mapeamento do item exato.

Servidor MCP falso em memoria (`tests/mercadophone_falso.py`), dados SINTETICOS.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import httpx
import pytest

from app.adapters.outbound.mercadophone.cliente import ClienteMercadoPhone, MercadoPhoneIndisponivel
from app.adapters.outbound.mercadophone.conferencia import ConferenciaItemMercadoPhone
from app.application.config.memoria import MemoriaConexaoErp
from app.application.estoque import EstoqueIndisponivel
from app.application.estoque_ao_vivo import ConferenciaItemErp, SituacaoAoVivo
from app.application.relogio import RelogioFalso
from app.domain.conexao_erp import ConexaoErp
from app.domain.estoque import Condicao, ItemEstoque
from app.domain.valores import Capacidade, Dinheiro, ModeloAparelho
from tests.mercadophone_falso import CHAVE, URL, McpFalso, item

LOJA = uuid4()


def local(sku: str, marca: str = "Apple", modelo: str = "iPhone 15 Pro") -> ItemEstoque:
    return ItemEstoque(
        sku=sku,
        modelo=ModeloAparelho.de(modelo, marca),
        capacidade=Capacidade("256gb"),
        cor="Preto",
        condicao=Condicao.SEMINOVO,
        preco_pix=Dinheiro.de(Decimal("4200")),
        quantidade=1,
    )


async def montar(
    mcp: McpFalso,
    *,
    conexao: ConexaoErp | None | str = "ativa",
    cliente: bool = True,
) -> ConferenciaItemMercadoPhone:
    conexoes = MemoriaConexaoErp()
    if conexao == "ativa":
        conexao = ConexaoErp(loja_id=LOJA, system_unit_id=4, filtro_loja="Loja A", ativo=True)
    if isinstance(conexao, ConexaoErp):
        await conexoes.salvar(conexao)
    http = ClienteMercadoPhone(mcp.cliente_http(), URL, CHAVE, relogio=RelogioFalso())
    return ConferenciaItemMercadoPhone(conexoes, lambda: http if cliente else None)


def test_implementa_a_porta() -> None:
    conferencia: ConferenciaItemErp = ConferenciaItemMercadoPhone(MemoriaConexaoErp(), lambda: None)
    assert conferencia is not None


async def test_item_disponivel_devolve_a_linha_do_erp_com_o_id_do_produto() -> None:
    mcp = McpFalso({4: [item(7, sku="TESTE-A", preco=4300)]})

    r = await (await montar(mcp)).conferir(LOJA, local("TESTE-A"))

    assert r.situacao is SituacaoAoVivo.DISPONIVEL
    assert r.linha is not None
    assert (r.linha.sku, r.linha.preco_pix.valor, r.linha.erp_produto_id) == (
        "TESTE-A",
        Decimal("4300.00"),
        7,
    )


async def test_uma_unica_chamada_filtrada_por_sku_e_unidade_sem_list_brands() -> None:
    mcp = McpFalso({4: [item(7, sku="TESTE-A")]})

    await (await montar(mcp)).conferir(LOJA, local("TESTE-A"))

    assert len(mcp.chamadas) == 1
    nome, args = mcp.chamadas[0]
    assert nome == "list_inventory"
    assert args["sku"] == "TESTE-A" and args["system_unit_id"] == 4


async def test_busca_parcial_do_erp_so_vale_pelo_sku_exato() -> None:
    mcp = McpFalso({4: [item(1, sku="TESTE-A10", preco=1), item(2, sku="TESTE-A", preco=4300)]})

    r = await (await montar(mcp)).conferir(LOJA, local("TESTE-A"))

    assert r.linha is not None and r.linha.erp_produto_id == 2


async def test_so_com_parciais_o_item_foi_vendido() -> None:
    mcp = McpFalso({4: [item(1, sku="TESTE-A10")]})

    r = await (await montar(mcp)).conferir(LOJA, local("TESTE-A"))

    assert r.situacao is SituacaoAoVivo.INDISPONIVEL and r.linha is None


async def test_sku_ausente_no_erp_e_vendido() -> None:
    r = await (await montar(McpFalso({4: []}))).conferir(LOJA, local("TESTE-A"))
    assert r.situacao is SituacaoAoVivo.INDISPONIVEL


async def test_quantidade_zero_no_erp_e_indisponivel() -> None:
    mcp = McpFalso({4: [item(7, sku="TESTE-A", quantidade=0)]})
    # o ERP real nem devolve quantidade 0 por padrao; o fake devolve se o filtro nao a esconder
    r = await (await montar(mcp)).conferir(LOJA, local("TESTE-A"))
    assert r.situacao is SituacaoAoVivo.INDISPONIVEL


async def test_item_reservado_ou_indisponivel_no_erp_nao_e_ofertavel() -> None:
    mcp = McpFalso({4: [item(7, sku="TESTE-A", disponibilidade="Vendido")]})
    r = await (await montar(mcp)).conferir(LOJA, local("TESTE-A"))
    assert r.situacao is SituacaoAoVivo.INDISPONIVEL


async def test_item_sem_preco_no_erp_nao_e_ofertavel() -> None:
    mcp = McpFalso({4: [item(7, sku="TESTE-A", preco=0)]})
    r = await (await montar(mcp)).conferir(LOJA, local("TESTE-A"))
    assert r.situacao is SituacaoAoVivo.INDISPONIVEL


async def test_item_que_passou_para_outra_loja_nao_e_desta_loja() -> None:
    mcp = McpFalso({4: [item(7, sku="TESTE-A", obs="Loja B")]})
    r = await (await montar(mcp)).conferir(LOJA, local("TESTE-A"))
    assert r.situacao is SituacaoAoVivo.INDISPONIVEL


async def test_marca_vem_da_linha_local_sem_chamar_list_brands() -> None:
    mcp = McpFalso({4: [item(7, sku="TESTE-A", modelo="GALAXY S24", marca_id=502)]})

    r = await (await montar(mcp)).conferir(LOJA, local("TESTE-A", "Samsung", "Galaxy S24"))

    assert r.linha is not None and r.linha.modelo.marca == "Samsung"
    assert [n for n, _ in mcp.chamadas] == ["list_inventory"]


@pytest.mark.parametrize("conexao", [None, "inativa"])
async def test_sem_conexao_ativa_nem_chama_o_erp(conexao: object) -> None:
    mcp = McpFalso({4: [item(7, sku="TESTE-A")]})
    if conexao == "inativa":
        conexao = ConexaoErp(loja_id=LOJA, system_unit_id=4, ativo=False)

    r = await (await montar(mcp, conexao=conexao)).conferir(LOJA, local("TESTE-A"))  # type: ignore[arg-type]

    assert r.situacao is SituacaoAoVivo.NAO_CONFERIDO
    assert mcp.chamadas == []


async def test_sem_chave_do_servidor_nao_confere() -> None:
    mcp = McpFalso({4: [item(7, sku="TESTE-A")]})

    r = await (await montar(mcp, cliente=False)).conferir(LOJA, local("TESTE-A"))

    assert r.situacao is SituacaoAoVivo.NAO_CONFERIDO
    assert mcp.chamadas == []


async def test_erp_com_erro_5xx_levanta_estoque_indisponivel() -> None:
    class Fora(McpFalso):
        def __call__(self, request: httpx.Request) -> httpx.Response:
            if b"tools/call" in request.content:
                return httpx.Response(503)
            return super().__call__(request)

    with pytest.raises(EstoqueIndisponivel) as exc:
        await (await montar(Fora({4: []}))).conferir(LOJA, local("TESTE-A"))
    assert isinstance(exc.value, MercadoPhoneIndisponivel)


async def test_timeout_de_rede_levanta_estoque_indisponivel() -> None:
    class Lento(McpFalso):
        def __call__(self, request: httpx.Request) -> httpx.Response:
            if b"tools/call" in request.content:
                raise httpx.ReadTimeout("lento", request=request)
            return super().__call__(request)

    with pytest.raises(EstoqueIndisponivel):
        await (await montar(Lento({4: []}))).conferir(LOJA, local("TESTE-A"))
