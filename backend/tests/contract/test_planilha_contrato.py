"""Aplica a suite de contrato da EstoquePort ao PlanilhaAdapter."""

from collections.abc import Mapping
from uuid import UUID

import pytest

from app.adapters.outbound.estoque.memoria import FonteEstoqueEmMemoria
from app.adapters.outbound.estoque.planilha import PlanilhaAdapter
from app.application.estoque import EstoquePort
from app.domain.estoque import ItemEstoque
from tests.contract.estoque_contrato import ContratoEstoque, CriarAdaptador


class TestPlanilhaContrato(ContratoEstoque):
    @pytest.fixture
    def criar_adaptador(self) -> CriarAdaptador:
        def _criar(itens_por_loja: Mapping[UUID, list[ItemEstoque]]) -> EstoquePort:
            return PlanilhaAdapter(FonteEstoqueEmMemoria(dict(itens_por_loja)))

        return _criar


def test_planilha_nao_suporta_reserva_nem_webhook() -> None:
    capacidades = PlanilhaAdapter(FonteEstoqueEmMemoria({})).capacidades
    assert capacidades.suporta_reserva is False
    assert capacidades.suporta_webhook is False
