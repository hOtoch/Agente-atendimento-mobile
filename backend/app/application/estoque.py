"""Portas de estoque: `EstoquePort` (consulta) e `FonteEstoqueLocal` (dados locais)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from app.domain.estoque import ItemEstoque
from app.domain.valores import Capacidade, ModeloAparelho


class EstoqueIndisponivel(Exception):
    """A fonte de estoque falhou (timeout, erro de rede, ERP fora)."""


@dataclass(frozen=True, slots=True)
class CapacidadesEstoque:
    """Recursos opcionais que o adaptador declara suportar."""

    suporta_reserva: bool
    suporta_webhook: bool


class EstoquePort(Protocol):
    @property
    def capacidades(self) -> CapacidadesEstoque: ...

    async def buscar(
        self,
        loja_id: UUID,
        modelo: str | ModeloAparelho,
        capacidade: Capacidade | None = None,
        cor: str | None = None,
    ) -> list[ItemEstoque]:
        """Itens disponiveis (quantidade > 0). Levanta `EstoqueIndisponivel` se a fonte falhar."""
        ...

    async def obter(self, loja_id: UUID, sku: str) -> ItemEstoque | None:
        """Item pelo SKU (inclusive esgotado) ou None se nao existir na loja."""
        ...


class FonteEstoqueLocal(Protocol):
    """Lista o estoque local de uma loja (banco, planilha importada, memoria)."""

    async def listar(self, loja_id: UUID) -> list[ItemEstoque]: ...
