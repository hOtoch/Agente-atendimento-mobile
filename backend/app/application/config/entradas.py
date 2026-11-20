"""Entradas (comandos) dos casos de uso: valores primitivos, ainda nao validados."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID


@dataclass(frozen=True, slots=True)
class EntradaPreco:
    max_parcelas: int
    repassa_taxa: bool
    desconto_pix_tipo: str
    desconto_pix_valor: Decimal | None
    aceita_entrada_mais_cartao: bool
    desconto_teto: Decimal
    desconto_degrau: Decimal
    oportunidade_ativa: bool
    oportunidade_dias_minimos: int
    oportunidade_valor: Decimal
    oportunidade_conta_no_teto: bool


@dataclass(frozen=True, slots=True)
class EntradaTaxa:
    chave: int | str
    bandeira: str
    taxa_pct: Decimal | None
    """None = "igual" (usa a Mastercard)."""


@dataclass(frozen=True, slots=True)
class EntradaLinhaTroca:
    marca: str
    modelo: str
    capacidade_gb: int
    valor_sem_detalhes: Decimal
    desconto_tela: Decimal | None
    desconto_tela_sem: bool
    desconto_traseira: Decimal | None
    desconto_traseira_sem: bool
    desconto_carcaca: Decimal | None
    desconto_carcaca_sem: bool
    desconto_bateria: Decimal | None
    desconto_bateria_sem: bool
    limite_bateria_pct: int


@dataclass(frozen=True, slots=True)
class EntradaLinhaEstoque:
    sku: str
    marca: str
    modelo: str
    capacidade_gb: int
    cor: str
    condicao: str
    preco_pix: Decimal
    quantidade: int
    bateria_pct: int | None


@dataclass(frozen=True, slots=True)
class EntradaLinhaMapeamento:
    sku_externo: str
    marca: str
    modelo: str
    capacidade_gb: int
    cor: str
    condicao: str


@dataclass(frozen=True, slots=True)
class EntradaVendedor:
    id: UUID | None
    """None = vendedor novo; com id = atualiza o existente da loja."""
    nome: str
    telefone: str | None
    peso_percentual: Decimal
    ativo: bool = True
