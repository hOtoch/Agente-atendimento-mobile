"""Politica de desconto por cliente e regra da oportunidade unica (funcoes puras)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum

from app.domain.valores import Dinheiro


@dataclass(frozen=True, slots=True)
class PoliticaDesconto:
    """Desconto maximo por cliente (`teto`) liberado em passos de `degrau`.

    Se o teto nao for multiplo do degrau, o ultimo degrau e parcial: libera so
    o que falta ate o teto (ex.: teto 120, degrau 50 -> 50, 100, 120).
    """

    teto: Dinheiro
    degrau: Dinheiro

    def __post_init__(self) -> None:
        if self.degrau <= Dinheiro.zero():
            raise ValueError("degrau deve ser maior que zero")
        if self.teto < Dinheiro.zero():
            raise ValueError("teto nao pode ser negativo")


@dataclass(frozen=True, slots=True)
class EstadoDesconto:
    """Quanto ja foi liberado para um lead. Imutavel: cada liberacao gera novo estado."""

    liberado: Dinheiro = field(default_factory=Dinheiro.zero)


@dataclass(frozen=True, slots=True)
class TetoAtingido:
    """Resultado de `liberar_proximo` quando nao ha mais o que liberar."""

    total: Dinheiro


def liberar_proximo(
    politica: PoliticaDesconto, estado: EstadoDesconto
) -> tuple[EstadoDesconto, Dinheiro] | TetoAtingido:
    """Libera o proximo degrau. Retorna (novo estado, total liberado) ou `TetoAtingido`."""
    if estado.liberado >= politica.teto:
        return TetoAtingido(total=estado.liberado)
    total = min(estado.liberado + politica.degrau, politica.teto)
    return EstadoDesconto(liberado=total), total


class PedidoCliente(StrEnum):
    """O que o cliente pediu na negociacao."""

    MAIS_DESCONTO = "mais_desconto"
    BRINDE_OU_BENEFICIO = "brinde_ou_beneficio"


class MotivoPassagem(StrEnum):
    """Por que a negociacao passa para o vendedor."""

    ACIMA_DO_TETO = "acima_do_teto"
    BRINDE_OU_BENEFICIO = "brinde_ou_beneficio"


@dataclass(frozen=True, slots=True)
class DescontoLiberado:
    """Degrau liberado: `total` e o desconto acumulado e `estado` o novo estado do lead."""

    estado: EstadoDesconto
    total: Dinheiro


@dataclass(frozen=True, slots=True)
class PassarAoVendedor:
    """A IA nao negocia mais: passa ao vendedor, com o que ja foi liberado ao cliente."""

    motivo: MotivoPassagem
    liberado: Dinheiro


def decidir_pedido_desconto(
    politica: PoliticaDesconto, estado: EstadoDesconto, pedido: PedidoCliente
) -> DescontoLiberado | PassarAoVendedor:
    """Escada de desconto: libera o proximo degrau ate o teto; alem disso (ou brinde), vendedor."""
    if pedido is PedidoCliente.BRINDE_OU_BENEFICIO:
        return PassarAoVendedor(MotivoPassagem.BRINDE_OU_BENEFICIO, estado.liberado)
    liberado = liberar_proximo(politica, estado)
    if isinstance(liberado, TetoAtingido):
        return PassarAoVendedor(MotivoPassagem.ACIMA_DO_TETO, liberado.total)
    novo_estado, total = liberado
    return DescontoLiberado(estado=novo_estado, total=total)


@dataclass(frozen=True, slots=True)
class RegraOportunidadeUnica:
    """Oferta para antecipar a compra quando a data prevista esta distante.

    `conta_no_teto=False` (default): o valor soma por fora do teto da politica.
    """

    ativa: bool
    dias_minimos: int
    valor: Dinheiro
    conta_no_teto: bool = False

    def __post_init__(self) -> None:
        if self.dias_minimos < 0:
            raise ValueError("dias_minimos nao pode ser negativo")
        if self.valor < Dinheiro.zero():
            raise ValueError("valor nao pode ser negativo")


def oportunidade_unica(
    data_prevista: date, hoje: date, regra: RegraOportunidadeUnica
) -> Dinheiro | None:
    """Valor da oportunidade se a regra esta ativa e a data esta a MAIS de N dias de hoje."""
    if not regra.ativa:
        return None
    if (data_prevista - hoje).days > regra.dias_minimos:
        return regra.valor
    return None


def desconto_total(
    politica: PoliticaDesconto,
    estado: EstadoDesconto,
    oportunidade: Dinheiro | None,
    regra: RegraOportunidadeUnica,
) -> Dinheiro:
    """Desconto liberado + oportunidade; com `conta_no_teto` a soma e limitada ao teto."""
    extra = oportunidade if oportunidade is not None else Dinheiro.zero()
    soma = estado.liberado + extra
    if regra.conta_no_teto:
        return min(soma, politica.teto)
    return soma
