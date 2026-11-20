"""Caso de uso: atribuir um vendedor a um lead conforme os pesos da loja.

Os pesos sao lidos a cada chamada (mudanca no painel vale para o proximo lead). A
decisao e do dominio (`escolher_vendedor`); aqui so se orquestra leitura, trava e gravacao.
So grava `leads.vendedor_id`: quem muda o `dono` da conversa e o handoff.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Protocol
from uuid import UUID

from app.application.config.modelos import VendedorLoja
from app.domain.distribuicao import Candidato, SemVendedorDisponivel, escolher_vendedor


class LeadNaoEncontrado(Exception):
    def __init__(self, lead_id: object) -> None:
        super().__init__(f"lead nao encontrado: {lead_id}")
        self.lead_id = lead_id


class ListaVendedores(Protocol):
    async def listar(self, loja_id: UUID) -> Sequence[VendedorLoja]: ...


class AtribuicoesLead(Protocol):
    """Atribuicao de vendedores a leads de uma loja."""

    async def travar_loja(self, loja_id: UUID) -> None:
        """Serializa distribuicoes da mesma loja ate o fim da transacao corrente."""
        ...

    async def vendedor_atribuido(self, loja_id: UUID, lead_id: UUID) -> UUID | None:
        """Vendedor ja atribuido ao lead; `LeadNaoEncontrado` se o lead nao e da loja."""
        ...

    async def contar_por_vendedor(self, loja_id: UUID) -> Mapping[UUID, int]:
        """Leads atribuidos por vendedor da loja (todo o historico; sem vendedor = ausente)."""
        ...

    async def atribuir(self, loja_id: UUID, lead_id: UUID, vendedor_id: UUID) -> None: ...


class DistribuirLead:
    def __init__(self, vendedores: ListaVendedores, atribuicoes: AtribuicoesLead) -> None:
        self._vendedores = vendedores
        self._atribuicoes = atribuicoes

    async def executar(self, loja_id: UUID, lead_id: UUID) -> UUID | SemVendedorDisponivel:
        """Devolve o vendedor do lead (o ja atribuido, se houver) ou `SemVendedorDisponivel`.

        Nao faz commit: a trava da loja dura ate o commit/rollback do chamador, o que
        serializa distribuicoes concorrentes.
        """
        await self._atribuicoes.travar_loja(loja_id)
        existente = await self._atribuicoes.vendedor_atribuido(loja_id, lead_id)
        if existente is not None:
            return existente
        vendedores = await self._vendedores.listar(loja_id)
        # Divida: o schema nao tem horario por vendedor, entao todos estao "disponiveis".
        candidatos = [
            Candidato(v.id, v.peso_percentual, ativo=v.ativo, disponivel=True) for v in vendedores
        ]
        contagem = await self._atribuicoes.contar_por_vendedor(loja_id)
        escolha = escolher_vendedor(candidatos, contagem)
        if isinstance(escolha, SemVendedorDisponivel):
            return escolha
        await self._atribuicoes.atribuir(loja_id, lead_id, escolha)
        return escolha
