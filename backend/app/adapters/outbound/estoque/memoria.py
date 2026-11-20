"""Fonte de estoque em memoria, para testes."""

from __future__ import annotations

from uuid import UUID

from app.domain.estoque import ItemEstoque


class FonteEstoqueEmMemoria:
    """Implementa `FonteEstoqueLocal` sobre um dict `loja_id -> itens`."""

    def __init__(self, itens_por_loja: dict[UUID, list[ItemEstoque]]) -> None:
        self._itens = itens_por_loja

    async def listar(self, loja_id: UUID) -> list[ItemEstoque]:
        return list(self._itens.get(loja_id, []))
