"""Aplica a suite de contrato da EstoquePort ao decorator EstoqueConferidoAoVivo."""

from collections.abc import Mapping
from uuid import UUID

import pytest

from app.adapters.outbound.estoque.memoria import FonteEstoqueEmMemoria
from app.adapters.outbound.estoque.planilha import PlanilhaAdapter
from app.application.config.memoria import MemoriaEstoqueLocal
from app.application.estoque import EstoquePort
from app.application.estoque_ao_vivo import ConferenciaAoVivo, EstoqueConferidoAoVivo
from app.application.estoque_resiliente import EstoqueResiliente
from app.application.relogio import RelogioFalso
from app.domain.estoque import ItemEstoque
from tests.contract.estoque_contrato import ContratoEstoque, CriarAdaptador


class _SemErp:
    async def conferir(self, loja_id: UUID, item: ItemEstoque) -> ConferenciaAoVivo:
        return ConferenciaAoVivo.nao_conferido()


class TestAoVivoContrato(ContratoEstoque):
    @pytest.fixture
    def criar_adaptador(self) -> CriarAdaptador:
        def _criar(itens_por_loja: Mapping[UUID, list[ItemEstoque]]) -> EstoquePort:
            base = EstoqueResiliente(
                PlanilhaAdapter(FonteEstoqueEmMemoria(dict(itens_por_loja))), RelogioFalso()
            )
            return EstoqueConferidoAoVivo(base, _SemErp(), MemoriaEstoqueLocal())

        return _criar
