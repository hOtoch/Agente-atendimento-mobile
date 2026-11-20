"""Casos de uso da configuracao da loja (lida a cada turno: mudanca vale na proxima mensagem)."""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from uuid import UUID

from app.application.config import validacao
from app.application.config.entradas import (
    EntradaLinhaEstoque,
    EntradaLinhaMapeamento,
    EntradaLinhaTroca,
    EntradaPreco,
    EntradaTaxa,
    EntradaVendedor,
)
from app.application.config.modelos import (
    ConfigPreco,
    ErroCampo,
    ErrosDeValidacao,
    ItemChecklist,
    LinhaEstoqueLocal,
    LinhaMapeamentoSku,
    LojaNaoEncontrada,
    PerfilLoja,
    VendedorLoja,
)
from app.application.config.portas import (
    IntegracaoEstoque,
    RepositorioConfigLoja,
    RepositorioEstoqueLocal,
    RepositorioLojas,
    RepositorioMapeamentoSku,
    RepositorioVendedores,
)
from app.domain.bandeira import Bandeira
from app.domain.pagamento import PARCELAS_MIN, TabelaTaxas
from app.domain.troca import TabelaTroca

_CEM = Decimal(100)


class CasosDeUsoConfig:
    def __init__(
        self,
        *,
        lojas: RepositorioLojas,
        config: RepositorioConfigLoja,
        estoque: RepositorioEstoqueLocal,
        mapeamento: RepositorioMapeamentoSku,
        vendedores: RepositorioVendedores,
        integracao: IntegracaoEstoque,
    ) -> None:
        self.lojas = lojas
        self.config = config
        self.estoque = estoque
        self.mapeamento = mapeamento
        self.vendedores = vendedores
        self.integracao = integracao

    async def _loja(self, loja_id: UUID) -> None:
        if not await self.lojas.existe(loja_id):
            raise LojaNaoEncontrada(loja_id)

    async def criar_loja(self, nome: str) -> UUID:
        if not nome.strip():
            raise ErrosDeValidacao([ErroCampo("nome", "Informe o nome da loja.")])
        return await self.lojas.criar(nome.strip())

    # --- perfil -------------------------------------------------------------------------------

    async def obter_perfil(self, loja_id: UUID) -> PerfilLoja | None:
        await self._loja(loja_id)
        return await self.config.obter_perfil(loja_id)

    async def atualizar_perfil(self, loja_id: UUID, perfil: PerfilLoja) -> PerfilLoja:
        await self._loja(loja_id)
        validacao.validar_perfil(perfil)
        await self.config.salvar_perfil(loja_id, perfil)
        return perfil

    # --- preco --------------------------------------------------------------------------------

    async def obter_preco(self, loja_id: UUID) -> ConfigPreco | None:
        await self._loja(loja_id)
        return await self.config.obter_config_preco(loja_id)

    async def atualizar_preco(self, loja_id: UUID, entrada: EntradaPreco) -> ConfigPreco:
        await self._loja(loja_id)
        config = validacao.montar_config_preco(entrada)
        await self.config.salvar_config_preco(loja_id, config)
        return config

    # --- taxas --------------------------------------------------------------------------------

    async def obter_taxas(self, loja_id: UUID) -> TabelaTaxas:
        await self._loja(loja_id)
        return await self.config.obter_taxas(loja_id)

    async def atualizar_taxas(self, loja_id: UUID, entradas: Sequence[EntradaTaxa]) -> TabelaTaxas:
        await self._loja(loja_id)
        taxas = validacao.montar_taxas(entradas)
        await self.config.salvar_taxas(loja_id, taxas)
        return taxas

    # --- troca --------------------------------------------------------------------------------

    async def obter_troca(self, loja_id: UUID) -> TabelaTroca:
        await self._loja(loja_id)
        return await self.config.obter_tabela_troca(loja_id)

    async def atualizar_troca(
        self, loja_id: UUID, entradas: Sequence[EntradaLinhaTroca]
    ) -> TabelaTroca:
        await self._loja(loja_id)
        tabela = validacao.montar_tabela_troca(entradas)
        await self.config.salvar_tabela_troca(loja_id, tabela)
        return tabela

    # --- estoque local ------------------------------------------------------------------------

    async def obter_estoque(self, loja_id: UUID) -> list[LinhaEstoqueLocal]:
        await self._loja(loja_id)
        return await self.estoque.listar(loja_id)

    async def atualizar_estoque(
        self, loja_id: UUID, entradas: Sequence[EntradaLinhaEstoque]
    ) -> list[LinhaEstoqueLocal]:
        await self._loja(loja_id)
        linhas = validacao.montar_estoque(entradas)
        await self.estoque.substituir(loja_id, linhas)
        return linhas

    # --- mapeamento de SKU --------------------------------------------------------------------

    async def obter_mapeamento(self, loja_id: UUID) -> list[LinhaMapeamentoSku]:
        await self._loja(loja_id)
        return await self.mapeamento.listar(loja_id)

    async def atualizar_mapeamento(
        self, loja_id: UUID, entradas: Sequence[EntradaLinhaMapeamento]
    ) -> list[LinhaMapeamentoSku]:
        await self._loja(loja_id)
        linhas = validacao.montar_mapeamento(entradas)
        await self.mapeamento.substituir(loja_id, linhas)
        return linhas

    # --- vendedores ---------------------------------------------------------------------------

    async def obter_vendedores(self, loja_id: UUID) -> list[VendedorLoja]:
        await self._loja(loja_id)
        return await self.vendedores.listar(loja_id)

    async def atualizar_vendedores(
        self, loja_id: UUID, entradas: Sequence[EntradaVendedor]
    ) -> list[VendedorLoja]:
        """Substitui a lista: mantem ids, cria novos e desativa (nunca apaga) os ausentes."""
        await self._loja(loja_id)
        existentes = {v.id for v in await self.vendedores.listar(loja_id)}
        erros = validacao.validar_vendedores(entradas, existentes)
        if erros:
            raise ErrosDeValidacao(erros)
        return await self.vendedores.substituir(loja_id, entradas)

    # --- checklist ----------------------------------------------------------------------------

    async def checklist(self, loja_id: UUID) -> list[ItemChecklist]:
        await self._loja(loja_id)
        perfil = await self.config.obter_perfil(loja_id)
        preco = await self.config.obter_config_preco(loja_id)
        taxas = await self.config.obter_taxas(loja_id)
        troca = await self.config.obter_tabela_troca(loja_id)
        estoque = await self.estoque.listar(loja_id)
        pesos = await self.vendedores.pesos_ativos(loja_id)
        erp = await self.integracao.erp_configurado(loja_id)
        pendentes = await self.integracao.skus_externos_sem_mapeamento(loja_id)
        return [
            _item_perfil(perfil),
            _item_vendedores(pesos),
            _item_preco(preco),
            _item_taxas(preco, taxas),
            _item_troca(troca),
            _item_estoque(len(estoque), erp),
            _item_mapeamento(pendentes),
        ]


def _item_perfil(perfil: PerfilLoja | None) -> ItemChecklist:
    rotulo = "Perfil da loja"
    if perfil is None:
        return ItemChecklist("perfil", rotulo, False, "Perfil ainda não preenchido.")
    faltam = [
        nome
        for nome, valor in (
            ("nome", perfil.nome_exibicao),
            ("endereço", perfil.endereco),
            ("WhatsApp de contato", perfil.whatsapp_contato),
        )
        if not valor.strip()
    ]
    if faltam:
        return ItemChecklist("perfil", rotulo, False, "Falta preencher: " + ", ".join(faltam) + ".")
    return ItemChecklist("perfil", rotulo, True, "Perfil preenchido.")


def _item_vendedores(pesos: list[Decimal]) -> ItemChecklist:
    rotulo = "Vendedores e distribuição"
    if not pesos:
        return ItemChecklist("vendedores", rotulo, False, "Nenhum vendedor ativo cadastrado.")
    soma = sum(pesos, Decimal(0))
    if soma != _CEM:
        return ItemChecklist(
            "vendedores", rotulo, False, f"Os pesos somam {soma.normalize():f}%, devem somar 100%."
        )
    return ItemChecklist(
        "vendedores", rotulo, True, f"{len(pesos)} vendedor(es), pesos somam 100%."
    )


def _item_preco(preco: ConfigPreco | None) -> ItemChecklist:
    rotulo = "Regras de preço"
    if preco is None:
        return ItemChecklist("regras_preco", rotulo, False, "Regras de preço ainda não definidas.")
    return ItemChecklist(
        "regras_preco", rotulo, True, f"Até {preco.regras.max_parcelas}x no cartão."
    )


def _item_taxas(preco: ConfigPreco | None, taxas: TabelaTaxas) -> ItemChecklist:
    rotulo = "Taxas da maquininha"
    if preco is None:
        return ItemChecklist(
            "taxas", rotulo, False, "Defina as regras de preço (máximo de parcelas) primeiro."
        )
    maximo = preco.regras.max_parcelas
    faltam = [
        n
        for n in range(PARCELAS_MIN, maximo + 1)
        if taxas.taxas.get((n, Bandeira.MASTERCARD)) is None
    ]
    if faltam:
        return ItemChecklist(
            "taxas",
            rotulo,
            False,
            f"Faltam taxas da Mastercard em {len(faltam)} de {maximo} parcelas (1x a {maximo}x).",
        )
    return ItemChecklist("taxas", rotulo, True, f"Mastercard preenchida de 1x a {maximo}x.")


def _item_troca(troca: TabelaTroca) -> ItemChecklist:
    rotulo = "Tabela de troca"
    total = len(troca.linhas_apple) + len(troca.linhas_outras_marcas)
    if total == 0:
        return ItemChecklist("tabela_troca", rotulo, False, "Nenhuma linha na tabela de troca.")
    return ItemChecklist("tabela_troca", rotulo, True, f"{total} linha(s) cadastrada(s).")


def _item_estoque(itens: int, erp: bool) -> ItemChecklist:
    rotulo = "Estoque"
    if erp:
        return ItemChecklist("estoque", rotulo, True, "Estoque vem do ERP configurado.")
    if itens == 0:
        return ItemChecklist(
            "estoque", rotulo, False, "Nenhum item no estoque e nenhum ERP configurado."
        )
    return ItemChecklist("estoque", rotulo, True, f"{itens} item(ns) no estoque.")


def _item_mapeamento(pendentes: list[str]) -> ItemChecklist:
    rotulo = "Mapeamento de SKU"
    if pendentes:
        return ItemChecklist(
            "mapeamento_sku",
            rotulo,
            False,
            f"{len(pendentes)} SKU(s) externo(s) sem mapeamento.",
        )
    return ItemChecklist("mapeamento_sku", rotulo, True, "Nenhum SKU externo pendente.")
