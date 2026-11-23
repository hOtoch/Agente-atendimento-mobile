"""Estimativa/medicao de custo do eval (precos e calculo vivem em `app.domain.precos`)."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.application.llm import UsoTokens
from app.domain.precos import PRECOS, Preco, custo_de_tokens
from app.domain.precos import custo_usd as _custo_usd_modelo

__all__ = ["PRECOS", "Estimativa", "Preco", "custo_usd", "estimar_custo"]

# Premissas da estimativa (por turno de conversa). O agente faz ~2-3 chamadas por turno
# (ferramentas) e o prefixo cacheado (sistema + ferramentas + historico) domina a entrada.
TOKENS_AGENTE_POR_TURNO = (1_500, 400, 6_000, 1_000)  # entrada, saida, cache_leit, cache_escr
TOKENS_CLIENTE_POR_TURNO = (900, 80, 0, 0)


def custo_usd(uso: UsoTokens) -> Decimal | None:
    """Custo em US$ do uso medido; `None` se o modelo nao tem preco cadastrado."""
    return _custo_usd_modelo(
        uso.modelo, uso.entrada, uso.saida, uso.cache_leitura, uso.cache_escrita
    )


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
        agente=custo_de_tokens(PRECOS[modelo], *TOKENS_AGENTE_POR_TURNO) * n,
        cliente=custo_de_tokens(PRECOS[modelo_cliente], *TOKENS_CLIENTE_POR_TURNO) * n,
    )
