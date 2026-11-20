"""Adaptador de estoque sobre uma fonte local (planilha importada)."""

from __future__ import annotations

from uuid import UUID

from app.application.estoque import CapacidadesEstoque, FonteEstoqueLocal
from app.domain.estoque import ItemEstoque, filtrar
from app.domain.valores import Capacidade, ModeloAparelho


class PlanilhaAdapter:
    """Implementa `EstoquePort` lendo de uma `FonteEstoqueLocal`."""

    capacidades = CapacidadesEstoque(suporta_reserva=False, suporta_webhook=False)

    def __init__(self, fonte: FonteEstoqueLocal) -> None:
        self._fonte = fonte

    async def buscar(
        self,
        loja_id: UUID,
        modelo: str | ModeloAparelho,
        capacidade: Capacidade | None = None,
        cor: str | None = None,
    ) -> list[ItemEstoque]:
        return filtrar(await self._fonte.listar(loja_id), modelo, capacidade, cor)

    async def obter(self, loja_id: UUID, sku: str) -> ItemEstoque | None:
        for item in await self._fonte.listar(loja_id):
            if item.sku == sku:
                return item
        return None
