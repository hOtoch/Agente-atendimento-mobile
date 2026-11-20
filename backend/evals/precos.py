"""Precos (US$ por milhao de tokens) e estimativa/medicao de custo do eval."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.application.llm import UsoTokens

_MTOK = Decimal(1_000_000)


@dataclass(frozen=True, slots=True)
class Preco:
    entrada: Decimal
    saida: Decimal
    cache_leitura: Decimal
    cache_escrita: Decimal


PRECOS: dict[str, Preco] = {
    "claude-sonnet-5-5": Preco(Decimal("2.00"), Decimal("10.00"), Decimal("0.10"), Decimal("2.50")),
    "claude-haiku-5-5": Preco(Decimal("0.10"), Decimal("0.50"), Decimal("0.01"), Decimal("0.125")),
}

# Premissas da estimativa (por turno de conversa). O agente faz ~2-3 chamadas por turno
# (ferramentas) e o prefixo cacheado (sistema + ferramentas + historico) domina a entrada.
TOKENS_AGENTE_POR_TURNO = (1_500, 400, 6_000, 1_000)  # entrada, saida, cache_leit, cache_escr
TOKENS_CLIENTE_POR_TURNO = (900, 80, 0, 0)


def _custo(preco: Preco, entrada: int, saida: int, cache_leit: int, cache_escr: int) -> Decimal:
    return (
        Decimal(entrada) * preco.entrada
        + Decimal(saida) * preco.saida
        + Decimal(cache_leit) * preco.cache_leitura
        + Decimal(cache_escr) * preco.cache_escrita
    ) / _MTOK


def custo_usd(uso: UsoTokens) -> Decimal | None:
    """Custo em US$ do uso medido; `None` se o modelo nao tem preco cadastrado."""
    preco = PRECOS.get(uso.modelo)
    if preco is None:
        return None
    return _custo(preco, uso.entrada, uso.saida, uso.cache_leitura, uso.cache_escrita)


@dataclass(frozen=True, slots=True)
class Estimativa:
    agente: Decimal
    cliente: Decimal

    @property
    def total(self) -> Decimal:
        return self.agente + self.cliente


def estimar_custo(modelo: str, modelo_cliente: str, *, cenarios: int, turnos: int) -> Estimativa:
    """Teto de custo: cenarios x turnos maximos x tokens medios por turno x preco do modelo."""
    n = cenarios * turnos
    return Estimativa(
        agente=_custo(PRECOS[modelo], *TOKENS_AGENTE_POR_TURNO) * n,
        cliente=_custo(PRECOS[modelo_cliente], *TOKENS_CLIENTE_POR_TURNO) * n,
    )
