"""Implementacoes em memoria das portas (testes unitarios; sem IO)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from app.application.config.casos_de_uso import CasosDeUsoConfig
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

    async def atualizar_linha(
        self, loja_id: UUID, sku: str, linha: LinhaEstoqueLocal | None
    ) -> None:
        atuais = self._linhas.setdefault(loja_id, [])
        for i, atual in enumerate(atuais):
            if atual.sku == sku:
                if linha is None:
                    del atuais[i]
                else:
                    atuais[i] = linha
                return
        if linha is not None:
            atuais.append(linha)


class MemoriaMapeamentoSku:
    def __init__(self) -> None:
        self._linhas: dict[UUID, list[LinhaMapeamentoSku]] = {}

    async def listar(self, loja_id: UUID) -> list[LinhaMapeamentoSku]:
        return list(self._linhas.get(loja_id, []))

    async def substituir(self, loja_id: UUID, linhas: Sequence[LinhaMapeamentoSku]) -> None:
        self._linhas[loja_id] = list(linhas)


class MemoriaVendedores:
    def __init__(self) -> None:
        self._por_loja: dict[UUID, list[VendedorLoja]] = {}

    def definir(self, loja_id: UUID, pesos: Sequence[Decimal]) -> None:
        """Atalho de teste: vendedores ativos anonimos com esses pesos."""
        self._por_loja[loja_id] = [
            VendedorLoja(uuid4(), f"Vendedor {i + 1}", None, p, True) for i, p in enumerate(pesos)
        ]

    async def pesos_ativos(self, loja_id: UUID) -> list[Decimal]:
        return [v.peso_percentual for v in self._por_loja.get(loja_id, []) if v.ativo]

    async def listar(self, loja_id: UUID) -> list[VendedorLoja]:
        return list(self._por_loja.get(loja_id, []))

    async def substituir(
        self, loja_id: UUID, entradas: Sequence[EntradaVendedor]
    ) -> list[VendedorLoja]:
        atuais = {v.id: v for v in self._por_loja.get(loja_id, [])}
        resultado: dict[UUID, VendedorLoja] = {}
        for e in entradas:
            vid = e.id if e.id is not None else uuid4()
            codigo = atuais[vid].codigo_erp if vid in atuais else None
            resultado[vid] = VendedorLoja(
                vid,
                e.nome.strip(),
                (e.telefone or "").strip() or None,
                e.peso_percentual,
                e.ativo,
                codigo,
            )
        for vid, antigo in atuais.items():
            if vid not in resultado:
                resultado[vid] = replace(antigo, ativo=False)
        self._por_loja[loja_id] = list(resultado.values())
        return list(resultado.values())

    async def criar_do_erp(self, loja_id: UUID, codigo_erp: str, nome: str) -> VendedorLoja:
        novo = VendedorLoja(uuid4(), nome.strip(), None, Decimal(0), True, codigo_erp)
        self._por_loja.setdefault(loja_id, []).append(novo)
        return novo

    async def atualizar_do_erp(
        self, loja_id: UUID, vendedor_id: UUID, *, nome: str, ativo: bool
    ) -> None:
        lista = self._por_loja.get(loja_id, [])
        for i, v in enumerate(lista):
            if v.id == vendedor_id:
                lista[i] = replace(v, nome=nome.strip(), ativo=ativo)


class MemoriaConexaoErp:
    def __init__(self) -> None:
        self._por_loja: dict[UUID, ConexaoErp] = {}

    async def obter(self, loja_id: UUID) -> ConexaoErp | None:
        return self._por_loja.get(loja_id)

    async def salvar(self, conexao: ConexaoErp) -> None:
        atual = self._por_loja.get(conexao.loja_id)
        if atual is not None:  # o status da sincronizacao sobrevive a regravacao da config
            conexao = replace(
                conexao,
                ultima_sincronizacao_em=atual.ultima_sincronizacao_em,
                ultimo_status=atual.ultimo_status,
                ultimo_relatorio=atual.ultimo_relatorio,
            )
        self._por_loja[conexao.loja_id] = conexao

    async def registrar_sincronizacao(
        self, loja_id: UUID, *, em: datetime, status: str, relatorio: Mapping[str, Any] | None
    ) -> None:
        atual = self._por_loja.get(loja_id)
        if atual is not None:
            self._por_loja[loja_id] = replace(
                atual, ultima_sincronizacao_em=em, ultimo_status=status, ultimo_relatorio=relatorio
            )

    async def listar_ativas(self) -> list[ConexaoErp]:
        return [c for c in self._por_loja.values() if c.ativo]


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
