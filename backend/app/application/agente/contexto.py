"""Contexto de execucao das ferramentas e o erro amigavel que elas devolvem ao LLM."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any
from uuid import UUID

from app.application.config.casos_de_uso import CasosDeUsoConfig
from app.application.estoque import EstoquePort


@dataclass(frozen=True, slots=True)
class ContextoFerramentas:
    """Tudo que as ferramentas precisam de fora: loja, lead, estoque, config (lida a cada turno)."""

    loja_id: UUID
    lead_id: UUID
    estoque: EstoquePort
    config: CasosDeUsoConfig
    hoje: date


class ErroFerramenta(Exception):
    """Entrada invalida ou situacao que o LLM precisa contornar; vira `erro=True` com mensagem."""

    def __init__(self, mensagem: str, **extras: Any) -> None:
        super().__init__(mensagem)
        self.extras = extras
