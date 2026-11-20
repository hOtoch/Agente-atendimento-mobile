"""Aplica a suite de contrato da EstoquePort ao ErpSimuladoAdapter (ERP falso via respx)."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from uuid import UUID

import httpx
import pytest
import respx

from app.adapters.outbound.estoque.erp_simulado import ErpSimuladoAdapter
from app.adapters.outbound.estoque.memoria import FonteMapeamentoEmMemoria
from app.application.estoque import EstoquePort
from app.domain.estoque import ItemEstoque, MapeamentoSku
from tests.contract.estoque_contrato import ContratoEstoque, CriarAdaptador
from tests.erp_falso import BASE_URL, TOKEN, montar_erp, produto


class TestErpSimuladoContrato(ContratoEstoque):
    @pytest.fixture
    async def criar_adaptador(self) -> AsyncIterator[CriarAdaptador]:
        clientes: list[httpx.AsyncClient] = []
        with respx.mock(assert_all_called=False) as router:

            def _criar(itens_por_loja: Mapping[UUID, list[ItemEstoque]]) -> EstoquePort:
                produtos = []
                mapeamentos: dict[UUID, dict[str, MapeamentoSku]] = {}
                for loja, itens in itens_por_loja.items():
                    mapeamentos[loja] = {}
                    for i in itens:
                        bat = f" BAT {i.bateria_pct}" if i.bateria_pct is not None else ""
                        # descricao opaca: so o mapeamento da loja diz o que o SKU e
                        produtos.append(
                            produto(
                                i.sku, f"ITEM {i.sku}{bat}", str(i.preco_pix.valor), i.quantidade
                            )
                        )
                        mapeamentos[loja][i.sku] = MapeamentoSku(
                            sku_externo=i.sku,
                            modelo=i.modelo,
                            capacidade=i.capacidade,
                            cor=i.cor,
                            condicao=i.condicao,
                        )
                montar_erp(router, produtos)
                cliente = httpx.AsyncClient()
                clientes.append(cliente)
                return ErpSimuladoAdapter(
                    cliente, BASE_URL, TOKEN, FonteMapeamentoEmMemoria(mapeamentos)
                )

            yield _criar
        for c in clientes:
            await c.aclose()


def test_nao_suporta_reserva_nem_webhook() -> None:
    adaptador = ErpSimuladoAdapter(
        httpx.AsyncClient(), BASE_URL, TOKEN, FonteMapeamentoEmMemoria({})
    )
    assert adaptador.capacidades.suporta_reserva is False
    assert adaptador.capacidades.suporta_webhook is False
