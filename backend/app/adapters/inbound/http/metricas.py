"""Rota REST das metricas de desempenho do agente (tela de desempenho da IA)."""

from __future__ import annotations

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.adapters.inbound.http.schemas_metricas import MetricasSchema, metricas_para_schema
from app.application.metricas import MetricasAgente
from app.infra.dependencias import get_metricas_agente, loja_autorizada

router = APIRouter(tags=["metricas"], dependencies=[Depends(loja_autorizada)])

Casos = Annotated[MetricasAgente, Depends(get_metricas_agente)]


@router.get("/lojas/{loja_id}/metricas", response_model=MetricasSchema)
async def obter_metricas(
    loja_id: UUID,
    casos: Casos,
    de: Annotated[
        date | None, Query(description="Primeiro dia (AAAA-MM-DD, America/Sao_Paulo).")
    ] = None,
    ate: Annotated[
        date | None, Query(description="Ultimo dia, inclusive (AAAA-MM-DD). Padrao: hoje.")
    ] = None,
) -> MetricasSchema:
    """Desempenho da IA no periodo (padrao: ultimos 30 dias), com comparacao ao periodo anterior.

    O periodo anterior tem o mesmo tamanho e termina na vespera de `de`. Maximo de 366 dias.
    """
    return metricas_para_schema(await casos.executar(loja_id, de, ate))
