"""Rotas REST da configuracao do follow-up automatico (tela Configuracoes do painel)."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.inbound.http.schemas_followup import FollowupSchema
from app.application.followup import ConfigurarFollowup, EntradaFollowup
from app.domain.followup import ConfigFollowup
from app.infra.dependencias import get_configurar_followup, get_session, loja_autorizada

router = APIRouter(tags=["config"], dependencies=[Depends(loja_autorizada)])

Casos = Annotated[ConfigurarFollowup, Depends(get_configurar_followup)]
Sessao = Annotated[AsyncSession, Depends(get_session)]


def _out(c: ConfigFollowup) -> FollowupSchema:
    return FollowupSchema(
        ligado=c.ligado,
        horas_por_etapa={e.value: h for e, h in c.horas_por_etapa.items()},
        max_tentativas=c.max_tentativas,
        intervalo_horas=c.intervalo_horas,
        hora_inicio=c.hora_inicio,
        hora_fim=c.hora_fim,
        max_dias_parado=c.max_dias_parado,
    )


def _entrada(c: FollowupSchema) -> EntradaFollowup:
    return EntradaFollowup(
        ligado=c.ligado,
        horas_por_etapa=c.horas_por_etapa,
        max_tentativas=c.max_tentativas,
        intervalo_horas=c.intervalo_horas,
        hora_inicio=c.hora_inicio,
        hora_fim=c.hora_fim,
        max_dias_parado=c.max_dias_parado,
    )


@router.get("/lojas/{loja_id}/config/followup", response_model=FollowupSchema)
async def obter_followup(loja_id: UUID, casos: Casos) -> FollowupSchema:
    return _out(await casos.obter(loja_id))


@router.put("/lojas/{loja_id}/config/followup", response_model=FollowupSchema)
async def atualizar_followup(
    loja_id: UUID, corpo: FollowupSchema, casos: Casos, sessao: Sessao
) -> FollowupSchema:
    config = await casos.atualizar(loja_id, _entrada(corpo))
    await sessao.commit()
    return _out(config)
