"""Fonte de estoque em memoria, para testes."""

from __future__ import annotations

from uuid import UUID

from app.domain.estoque import ItemEstoque, MapeamentoSku


class FonteEstoqueEmMemoria:
    """Implementa `FonteEstoqueLocal` sobre um dict `loja_id -> itens`."""

    def __init__(self, itens_por_loja: dict[UUID, list[ItemEstoque]]) -> None:
        self._itens = itens_por_loja

    async def listar(self, loja_id: UUID) -> list[ItemEstoque]:
        return list(self._itens.get(loja_id, []))


class FonteMapeamentoEmMemoria:
    """Implementa `FonteMapeamentoSku` sobre um dict `loja_id -> {sku_externo: mapeamento}`."""

    def __init__(self, mapeamentos_por_loja: dict[UUID, dict[str, MapeamentoSku]]) -> None:
        self._mapeamentos = mapeamentos_por_loja

    async def listar(self, loja_id: UUID) -> dict[str, MapeamentoSku]:
        return dict(self._mapeamentos.get(loja_id, {}))
