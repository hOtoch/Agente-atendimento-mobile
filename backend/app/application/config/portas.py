"""Portas (Protocol) da configuracao da loja."""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from app.application.config.modelos import (
    ConfigPreco,
    LinhaEstoqueLocal,
    LinhaMapeamentoSku,
    PerfilLoja,
)
from app.domain.pagamento import TabelaTaxas
from app.domain.troca import TabelaTroca


class RepositorioLojas(Protocol):
    async def criar(self, nome: str) -> UUID: ...

    async def existe(self, loja_id: UUID) -> bool: ...


class RepositorioConfigLoja(Protocol):
    """Leitura/gravacao dos blocos de configuracao. `obter_*` reflete a ultima gravacao."""

    async def obter_perfil(self, loja_id: UUID) -> PerfilLoja | None: ...

    async def salvar_perfil(self, loja_id: UUID, perfil: PerfilLoja) -> None: ...

    async def obter_config_preco(self, loja_id: UUID) -> ConfigPreco | None: ...

    async def salvar_config_preco(self, loja_id: UUID, config: ConfigPreco) -> None: ...

    async def obter_taxas(self, loja_id: UUID) -> TabelaTaxas: ...

    async def salvar_taxas(self, loja_id: UUID, taxas: TabelaTaxas) -> None: ...

    async def obter_tabela_troca(self, loja_id: UUID) -> TabelaTroca: ...

    async def salvar_tabela_troca(self, loja_id: UUID, tabela: TabelaTroca) -> None: ...


class RepositorioEstoqueLocal(Protocol):
    async def listar(self, loja_id: UUID) -> list[LinhaEstoqueLocal]: ...

    async def substituir(self, loja_id: UUID, linhas: Sequence[LinhaEstoqueLocal]) -> None: ...


class RepositorioMapeamentoSku(Protocol):
    async def listar(self, loja_id: UUID) -> list[LinhaMapeamentoSku]: ...

    async def substituir(self, loja_id: UUID, linhas: Sequence[LinhaMapeamentoSku]) -> None: ...


class LeitorVendedores(Protocol):
    """Leitura minima de vendedores para o checklist (CRUD de vendedores e de outra issue)."""

    async def pesos_ativos(self, loja_id: UUID) -> list[Decimal]: ...


class IntegracaoEstoque(Protocol):
    """Gancho do checklist para o ERP (issues de estoque): configurado? SKUs sem mapeamento?"""

    async def erp_configurado(self, loja_id: UUID) -> bool: ...

    async def skus_externos_sem_mapeamento(self, loja_id: UUID) -> list[str]: ...


class SemIntegracaoEstoque:
    """Implementacao nula: nenhum ERP configurado, nenhum SKU externo pendente."""

    async def erp_configurado(self, loja_id: UUID) -> bool:
        return False

    async def skus_externos_sem_mapeamento(self, loja_id: UUID) -> list[str]:
        return []
