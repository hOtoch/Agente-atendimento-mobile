"""Schemas da API de configuracao do follow-up automatico."""

from __future__ import annotations

from datetime import time

from pydantic import BaseModel, Field, field_serializer


class FollowupSchema(BaseModel):
    ligado: bool
    horas_por_etapa: dict[str, int] = Field(default_factory=dict)
    """Etapa do kanban (`interesse_qualificado`...) -> horas parado ate o 1o follow-up."""
    max_tentativas: int
    intervalo_horas: int
    hora_inicio: time
    """Inicio do horario comercial (America/Sao_Paulo), `HH:MM`."""
    hora_fim: time
    max_dias_parado: int

    @field_serializer("hora_inicio", "hora_fim")
    def _hora(self, valor: time) -> str:
        return valor.strftime("%H:%M")
