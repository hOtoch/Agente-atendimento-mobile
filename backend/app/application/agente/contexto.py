"""Contexto de execucao das ferramentas e o erro amigavel que elas devolvem ao LLM."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

from app.application.config.casos_de_uso import CasosDeUsoConfig
from app.application.estoque import EstoquePort


def _agora() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class ContextoFerramentas:
    """Tudo que as ferramentas precisam de fora: loja, lead, estoque, config (lida a cada turno)."""

    loja_id: UUID
    lead_id: UUID
    estoque: EstoquePort
    config: CasosDeUsoConfig
    hoje: date
    agora: Callable[[], datetime] = _agora
    """Relogio do fechamento do acordo (injetavel nos testes)."""
    fala_do_cliente: str | None = None
    """O que o cliente escreveu neste turno (o codigo confere o que o modelo diz que ele disse).
    None: ferramenta rodando fora de uma conversa (testes isolados), sem essa conferencia."""


class ErroFerramenta(Exception):
    """Entrada invalida ou situacao que o LLM precisa contornar; vira `erro=True` com mensagem."""

    def __init__(self, mensagem: str, **extras: Any) -> None:
        super().__init__(mensagem)
        self.extras = extras
