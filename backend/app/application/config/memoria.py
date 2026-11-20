"""Implementacoes em memoria das portas (testes unitarios; sem IO)."""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from uuid import UUID, uuid4

from app.application.config.casos_de_uso import CasosDeUsoConfig
from app.application.config.modelos import (
    ConfigPreco,
    LinhaEstoqueLocal,
    LinhaMapeamentoSku,
    PerfilLoja,
)
from app.domain.pagamento import TabelaTaxas
from app.domain.troca import TabelaTroca


class MemoriaLojas:
    def __init__(self) -> None:
        self.nomes: dict[UUID, str] = {}

    async def criar(self, nome: str) -> UUID:
        loja_id = uuid4()
        self.nomes[loja_id] = nome
        return loja_id

    async def existe(self, loja_id: UUID) -> bool:
        return loja_id in self.nomes


class MemoriaConfigLoja:
    def __init__(self) -> None:
        self._perfil: dict[UUID, PerfilLoja] = {}
        self._preco: dict[UUID, ConfigPreco] = {}
        self._taxas: dict[UUID, TabelaTaxas] = {}
        self._troca: dict[UUID, TabelaTroca] = {}

    async def obter_perfil(self, loja_id: UUID) -> PerfilLoja | None:
        return self._perfil.get(loja_id)

    async def salvar_perfil(self, loja_id: UUID, perfil: PerfilLoja) -> None:
        self._perfil[loja_id] = perfil

    async def obter_config_preco(self, loja_id: UUID) -> ConfigPreco | None:
        return self._preco.get(loja_id)

    async def salvar_config_preco(self, loja_id: UUID, config: ConfigPreco) -> None:
        self._preco[loja_id] = config

    async def obter_taxas(self, loja_id: UUID) -> TabelaTaxas:
        return self._taxas.get(loja_id, TabelaTaxas({}))

    async def salvar_taxas(self, loja_id: UUID, taxas: TabelaTaxas) -> None:
        self._taxas[loja_id] = taxas

    async def obter_tabela_troca(self, loja_id: UUID) -> TabelaTroca:
        return self._troca.get(loja_id, TabelaTroca())

    async def salvar_tabela_troca(self, loja_id: UUID, tabela: TabelaTroca) -> None:
        self._troca[loja_id] = tabela


class MemoriaEstoqueLocal:
    def __init__(self) -> None:
        self._linhas: dict[UUID, list[LinhaEstoqueLocal]] = {}

    async def listar(self, loja_id: UUID) -> list[LinhaEstoqueLocal]:
        return list(self._linhas.get(loja_id, []))

    async def substituir(self, loja_id: UUID, linhas: Sequence[LinhaEstoqueLocal]) -> None:
        self._linhas[loja_id] = list(linhas)


class MemoriaMapeamentoSku:
    def __init__(self) -> None:
        self._linhas: dict[UUID, list[LinhaMapeamentoSku]] = {}

    async def listar(self, loja_id: UUID) -> list[LinhaMapeamentoSku]:
        return list(self._linhas.get(loja_id, []))

    async def substituir(self, loja_id: UUID, linhas: Sequence[LinhaMapeamentoSku]) -> None:
        self._linhas[loja_id] = list(linhas)


class MemoriaVendedores:
    def __init__(self) -> None:
        self._pesos: dict[UUID, list[Decimal]] = {}

    def definir(self, loja_id: UUID, pesos: Sequence[Decimal]) -> None:
        self._pesos[loja_id] = list(pesos)

    async def pesos_ativos(self, loja_id: UUID) -> list[Decimal]:
        return list(self._pesos.get(loja_id, []))


class MemoriaIntegracaoEstoque:
    def __init__(self) -> None:
        self.erp_ativo = False
        self.pendentes: list[str] = []

    async def erp_configurado(self, loja_id: UUID) -> bool:
        return self.erp_ativo

    async def skus_externos_sem_mapeamento(self, loja_id: UUID) -> list[str]:
        return list(self.pendentes)


def criar_casos_em_memoria() -> CasosDeUsoConfig:
    return CasosDeUsoConfig(
        lojas=MemoriaLojas(),
        config=MemoriaConfigLoja(),
        estoque=MemoriaEstoqueLocal(),
        mapeamento=MemoriaMapeamentoSku(),
        vendedores=MemoriaVendedores(),
        integracao=MemoriaIntegracaoEstoque(),
    )
