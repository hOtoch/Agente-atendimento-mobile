"""Calculo de pagamento: Pix, debito, credito parcelado e entrada + cartao.

Regras (context.md 3.2 e 3.3): `parcela = base * (1 + taxa/100) / n`, onde
`base = preco - desconto - troca - entrada` (nunca negativa). Sem repasse de taxa,
`parcela = base / n`. Dominio puro: sem IO.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Final, Literal

from app.domain.valores import Bandeira, Dinheiro

DEBITO: Final = "debito"
"""Chave da taxa de debito na tabela (no lugar do numero de parcelas)."""

type ChaveTaxa = int | Literal["debito"]

PARCELAS_MIN: Final = 1
PARCELAS_MAX: Final = 21
_CEM: Final = Decimal(100)


class PagamentoError(Exception):
    """Base dos erros de dominio do calculo de pagamento."""


class ParcelasInvalidas(PagamentoError):
    def __init__(self, parcelas: object) -> None:
        super().__init__(
            f"parcelas invalidas: {parcelas!r} (esperado {PARCELAS_MIN}..{PARCELAS_MAX})"
        )
        self.parcelas = parcelas


class ParcelasAcimaDoMaximo(PagamentoError):
    def __init__(self, parcelas: int, maximo: int) -> None:
        super().__init__(f"{parcelas}x excede o maximo da loja ({maximo}x)")
        self.parcelas = parcelas
        self.maximo = maximo


class EntradaNaoAceita(PagamentoError):
    def __init__(self) -> None:
        super().__init__("a loja nao aceita entrada + parcelas no cartao")


class EntradaInvalida(PagamentoError):
    def __init__(self, entrada: Dinheiro) -> None:
        super().__init__(f"entrada invalida: {entrada}")
        self.entrada = entrada


class TaxaNaoCadastrada(PagamentoError):
    def __init__(self, chave: ChaveTaxa, bandeira: Bandeira) -> None:
        super().__init__(f"taxa nao cadastrada para {chave} / {bandeira.value}")
        self.chave = chave
        self.bandeira = bandeira


@dataclass(frozen=True, slots=True)
class TabelaTaxas:
    """Taxa percentual por (parcelas 1..21 | DEBITO) x bandeira.

    Ausencia da entrada ou valor `None` significa "igual": usa a taxa da MASTERCARD.
    """

    taxas: Mapping[tuple[ChaveTaxa, Bandeira], Decimal | None]

    def taxa(self, parcelas_ou_debito: ChaveTaxa, bandeira: Bandeira) -> Decimal:
        proprio = self.taxas.get((parcelas_ou_debito, bandeira))
        if proprio is not None:
            return proprio
        referencia = self.taxas.get((parcelas_ou_debito, Bandeira.MASTERCARD))
        if referencia is None:
            raise TaxaNaoCadastrada(parcelas_ou_debito, bandeira)
        return referencia


@dataclass(frozen=True, slots=True)
class DescontoPixNenhum:
    """O preco a vista ja e o do Pix."""


@dataclass(frozen=True, slots=True)
class DescontoPixPercentual:
    percentual: Decimal

    def __post_init__(self) -> None:
        if not Decimal(0) <= self.percentual <= _CEM:
            raise ValueError(f"percentual de desconto Pix fora de 0..100: {self.percentual}")


@dataclass(frozen=True, slots=True)
class DescontoPixValor:
    valor: Dinheiro

    def __post_init__(self) -> None:
        if self.valor.negativo:
            raise ValueError(f"desconto Pix negativo: {self.valor}")


type DescontoPix = DescontoPixNenhum | DescontoPixPercentual | DescontoPixValor


@dataclass(frozen=True, slots=True)
class RegrasPreco:
    max_parcelas: int
    repassa_taxa: bool
    desconto_pix: DescontoPix
    aceita_entrada_mais_cartao: bool


@dataclass(frozen=True, slots=True)
class PixDinheiro:
    """Pagamento a vista (Pix ou dinheiro)."""


@dataclass(frozen=True, slots=True)
class Debito:
    bandeira: Bandeira


@dataclass(frozen=True, slots=True)
class Credito:
    parcelas: int
    bandeira: Bandeira


@dataclass(frozen=True, slots=True)
class EntradaMaisCredito:
    entrada: Dinheiro
    parcelas: int
    bandeira: Bandeira


type FormaPagamento = PixDinheiro | Debito | Credito | EntradaMaisCredito


class AvisoProposta(StrEnum):
    TROCA_COBRE_O_VALOR = "troca_cobre_o_valor"


@dataclass(frozen=True, slots=True)
class Proposta:
    forma: FormaPagamento
    base: Dinheiro
    """preco - desconto - troca - entrada (>= 0), antes do desconto Pix e da taxa."""
    entrada: Dinheiro
    total_pago: Dinheiro
    """entrada + valor_parcela * parcelas (o que o cliente de fato desembolsa)."""
    parcelas: int
    valor_parcela: Dinheiro
    taxa_aplicada_pct: Decimal
    aviso: AvisoProposta | None = None


def _validar_parcelas(parcelas: int, regras: RegrasPreco) -> None:
    if isinstance(parcelas, bool) or not isinstance(parcelas, int):
        raise ParcelasInvalidas(parcelas)
    if not PARCELAS_MIN <= parcelas <= PARCELAS_MAX:
        raise ParcelasInvalidas(parcelas)
    if parcelas > regras.max_parcelas:
        raise ParcelasAcimaDoMaximo(parcelas, regras.max_parcelas)


def _desconto_pix(base: Dinheiro, desconto: DescontoPix) -> Dinheiro:
    match desconto:
        case DescontoPixNenhum():
            return Dinheiro.zero()
        case DescontoPixPercentual(percentual=pct):
            return Dinheiro(base.valor * pct / _CEM)
        case DescontoPixValor(valor=valor):
            return min(valor, base)


def _parcelar(base: Dinheiro, taxa_pct: Decimal, parcelas: int) -> Dinheiro:
    # um unico arredondamento, no fim
    return Dinheiro(base.valor * (1 + taxa_pct / _CEM) / parcelas)


def calcular_pagamento(
    preco: Dinheiro,
    desconto: Dinheiro,
    troca: Dinheiro,
    forma: FormaPagamento,
    regras: RegrasPreco,
    taxas: TabelaTaxas,
) -> Proposta:
    """Calcula a proposta para uma forma de pagamento COMPLETA.

    Levanta `PagamentoError` (subclasses tipadas) para parcelas invalidas ou acima do
    maximo, entrada nao aceita/invalida e taxa nao cadastrada.
    """
    entrada = Dinheiro.zero()
    if isinstance(forma, EntradaMaisCredito):
        if not regras.aceita_entrada_mais_cartao:
            raise EntradaNaoAceita
        if forma.entrada.negativo:
            raise EntradaInvalida(forma.entrada)
        entrada = forma.entrada

    bruto = preco - desconto - troca - entrada
    aviso = AvisoProposta.TROCA_COBRE_O_VALOR if bruto.negativo else None
    base = bruto.nao_negativo()

    match forma:
        case PixDinheiro():
            total = base - _desconto_pix(base, regras.desconto_pix)
            return Proposta(forma, base, entrada, total, 1, total, Decimal(0), aviso)
        case Debito(bandeira=bandeira):
            parcelas = 1
            chave: ChaveTaxa = DEBITO
        case Credito(parcelas=parcelas, bandeira=bandeira):
            _validar_parcelas(parcelas, regras)
            chave = parcelas
        case EntradaMaisCredito(parcelas=parcelas, bandeira=bandeira):
            _validar_parcelas(parcelas, regras)
            chave = parcelas

    taxa = taxas.taxa(chave, bandeira) if regras.repassa_taxa else Decimal(0)
    valor_parcela = _parcelar(base, taxa, parcelas)
    total = entrada + valor_parcela * parcelas
    return Proposta(forma, base, entrada, total, parcelas, valor_parcela, taxa, aviso)


def simular_opcoes(
    preco: Dinheiro,
    desconto: Dinheiro,
    troca: Dinheiro,
    regras: RegrasPreco,
    taxas: TabelaTaxas,
    bandeira: Bandeira = Bandeira.MASTERCARD,
) -> list[Proposta]:
    """Pix + credito em 1x, 10x, 12x e `max_parcelas` (sem duplicatas, ate o maximo)."""
    quantidades = sorted({n for n in (1, 10, 12, regras.max_parcelas) if n <= regras.max_parcelas})
    formas: list[FormaPagamento] = [PixDinheiro()]
    formas += [Credito(n, bandeira) for n in quantidades]
    return [calcular_pagamento(preco, desconto, troca, f, regras, taxas) for f in formas]
