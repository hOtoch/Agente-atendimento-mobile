"""Portas (Protocol) da configuracao da loja."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from decimal import Decimal
from typing import Any, Protocol
from uuid import UUID

from app.application.config.entradas import EntradaVendedor
from app.application.config.modelos import (
    ConfigPreco,
    LinhaEstoqueLocal,
    LinhaMapeamentoSku,
    PerfilLoja,
    VendedorLoja,
)
from app.domain.conexao_erp import ConexaoErp
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
    """Leitura minima de vendedores para o checklist."""

    async def pesos_ativos(self, loja_id: UUID) -> list[Decimal]: ...


class RepositorioVendedores(LeitorVendedores, Protocol):
    """Vendedores da loja. Leads e conversas referenciam vendedor: nunca se apaga, so desativa."""

    async def listar(self, loja_id: UUID) -> list[VendedorLoja]: ...

    async def substituir(
        self, loja_id: UUID, entradas: Sequence[EntradaVendedor]
    ) -> list[VendedorLoja]:
        """Atualiza os que vierem com id, cria os sem id e desativa os ausentes."""
        ...

    async def criar_do_erp(self, loja_id: UUID, codigo_erp: str, nome: str) -> VendedorLoja:
        """Cria um vendedor vindo do ERP: ativo, sem telefone e com peso 0."""
        ...

    async def atualizar_do_erp(
        self, loja_id: UUID, vendedor_id: UUID, *, nome: str, ativo: bool
    ) -> None:
        """Muda so nome e ativo (nunca telefone, peso ou `codigo_erp`). Id de outra loja: nada."""
        ...


class RepositorioConexaoErp(Protocol):
    """Conexao da loja com o ERP (uma por loja). A chave de acesso nao e guardada aqui."""

    async def obter(self, loja_id: UUID) -> ConexaoErp | None: ...

    async def salvar(self, conexao: ConexaoErp) -> None:
        """Upsert da configuracao; NAO mexe no status da ultima sincronizacao."""
        ...

    async def registrar_sincronizacao(
        self, loja_id: UUID, *, em: datetime, status: str, relatorio: Mapping[str, Any] | None
    ) -> None:
        """Grava o resultado da ultima sincronizacao. Sem conexao configurada, nao faz nada."""
        ...

    async def listar_ativas(self) -> list[ConexaoErp]:
        """Conexoes com `ativo=True` (todas as lojas), para o agendador da sincronizacao."""
        ...


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
