"""Aplica a suite de contrato da EstoquePort ao decorator EstoqueResiliente."""

from collections.abc import Mapping
from uuid import UUID

import pytest

from app.adapters.outbound.estoque.memoria import FonteEstoqueEmMemoria
from app.adapters.outbound.estoque.planilha import PlanilhaAdapter
from app.application.estoque import EstoquePort
from app.application.estoque_resiliente import EstoqueResiliente
from app.application.relogio import RelogioFalso
from app.domain.estoque import ItemEstoque
from tests.contract.estoque_contrato import ContratoEstoque, CriarAdaptador


class TestResilienteContrato(ContratoEstoque):
    @pytest.fixture
    def criar_adaptador(self) -> CriarAdaptador:
        def _criar(itens_por_loja: Mapping[UUID, list[ItemEstoque]]) -> EstoquePort:
            base = PlanilhaAdapter(FonteEstoqueEmMemoria(dict(itens_por_loja)))
            return EstoqueResiliente(base, RelogioFalso())

        return _criar
