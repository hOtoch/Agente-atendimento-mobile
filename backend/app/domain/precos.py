"""Precos por modelo (US$ por milhao de tokens) e custo do uso medido.

Funcoes puras com `Decimal`: o custo nunca e arredondado aqui (so na apresentacao). Modelo sem
preco cadastrado nao tem custo (`None`): nunca se inventa um valor.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

_MTOK = Decimal(1_000_000)


@dataclass(frozen=True, slots=True)
class Preco:
    """US$ por milhao de tokens, por tipo."""

    entrada: Decimal
    saida: Decimal
    cache_leitura: Decimal
    cache_escrita: Decimal


PRECOS: dict[str, Preco] = {
    "claude-sonnet-5-5": Preco(Decimal("2.00"), Decimal("10.00"), Decimal("0.10"), Decimal("2.50")),
    "claude-haiku-5-5": Preco(Decimal("0.10"), Decimal("0.50"), Decimal("0.01"), Decimal("0.125")),
}


def custo_de_tokens(
    preco: Preco, entrada: int, saida: int, cache_leitura: int, cache_escrita: int
) -> Decimal:
    """Custo em US$ de uma contagem de tokens, ao `preco` dado."""
    return (
        Decimal(entrada) * preco.entrada
        + Decimal(saida) * preco.saida
        + Decimal(cache_leitura) * preco.cache_leitura
        + Decimal(cache_escrita) * preco.cache_escrita
    ) / _MTOK


def custo_usd(
    modelo: str, entrada: int, saida: int, cache_leitura: int, cache_escrita: int
) -> Decimal | None:
    """Custo em US$ do uso; `None` se o modelo nao tem preco cadastrado."""
    preco = PRECOS.get(modelo)
    if preco is None:
        return None
    return custo_de_tokens(preco, entrada, saida, cache_leitura, cache_escrita)
