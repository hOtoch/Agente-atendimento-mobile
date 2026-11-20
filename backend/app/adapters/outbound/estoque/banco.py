"""Fonte de estoque local sobre o banco: `FonteEstoqueLocal` lendo `RepositorioEstoqueLocal`."""

from __future__ import annotations

from uuid import UUID

from app.application.config.portas import RepositorioEstoqueLocal
from app.domain.estoque import Condicao, ItemEstoque


class FonteEstoqueLocalSql:
    """Converte as linhas gravadas pelo importador/painel em `ItemEstoque` para o adaptador."""

    def __init__(self, repositorio: RepositorioEstoqueLocal) -> None:
        self._repositorio = repositorio

    async def listar(self, loja_id: UUID) -> list[ItemEstoque]:
        itens: list[ItemEstoque] = []
        for linha in await self._repositorio.listar(loja_id):
            condicao = Condicao(linha.condicao)
            itens.append(
                ItemEstoque(
                    sku=linha.sku,
                    modelo=linha.modelo,
                    capacidade=linha.capacidade,
                    cor=linha.cor or None,
                    condicao=condicao,
                    preco_pix=linha.preco_pix,
                    quantidade=linha.quantidade,
                    bateria_pct=linha.bateria_pct if condicao is Condicao.SEMINOVO else None,
                )
            )
        return itens
