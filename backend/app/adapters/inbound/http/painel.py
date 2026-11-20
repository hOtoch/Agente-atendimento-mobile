"""Rotas do painel do vendedor: kanban, detalhe, movimentos, handoff, mensagens e SSE."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.adapters.inbound.http import schemas_painel as s
from app.adapters.inbound.http.sse import SSE_HEADERS, eventos_sse
from app.adapters.outbound.barramento.painel import topico_painel
from app.application.canal import BarramentoMensagens
from app.application.config.modelos import LojaNaoEncontrada
from app.application.config.portas import RepositorioLojas
from app.application.painel.casos_de_uso import CasosPainel
from app.infra.dependencias import get_barramento, get_casos_painel, get_lojas

router = APIRouter(prefix="/lojas/{loja_id}", tags=["painel"])

Casos = Annotated[CasosPainel, Depends(get_casos_painel)]
Lojas = Annotated[RepositorioLojas, Depends(get_lojas)]


async def _exigir_loja(lojas: RepositorioLojas, loja_id: UUID) -> None:
    if not await lojas.existe(loja_id):
        raise LojaNaoEncontrada(loja_id)


@router.get(
    "/leads",
    response_model=s.KanbanSchema,
    summary="Leads agrupados por etapa",
    responses={404: {"model": s.ErrosSchema}},
)
async def listar_leads(loja_id: UUID, casos: Casos, lojas: Lojas) -> s.KanbanSchema:
    await _exigir_loja(lojas, loja_id)
    return s.KanbanSchema.de(await casos.kanban(loja_id))


@router.get(
    "/leads/{lead_id}",
    response_model=s.DetalheLeadSchema,
    summary="Detalhe do lead",
    responses={404: {"model": s.ErrosSchema}},
)
async def detalhe_lead(loja_id: UUID, lead_id: UUID, casos: Casos) -> s.DetalheLeadSchema:
    return s.DetalheLeadSchema.de(await casos.detalhe(loja_id, lead_id))


@router.post(
    "/leads/{lead_id}/etapa",
    response_model=s.CardLeadSchema,
    summary="Mover o lead de etapa (manual, pelo vendedor)",
    responses={
        404: {"model": s.ErrosSchema},
        409: {"model": s.ErrosSchema, "description": "Movimento recusado pelo kanban."},
    },
)
async def mover_etapa(
    loja_id: UUID, lead_id: UUID, corpo: s.MoverEtapaIn, casos: Casos
) -> s.CardLeadSchema:
    return s.CardLeadSchema.de(await casos.mover_etapa(loja_id, lead_id, corpo.etapa))


@router.post(
    "/leads/{lead_id}/assumir",
    response_model=s.CardLeadSchema,
    summary="Vendedor assume a conversa (a IA fica em silencio)",
    responses={404: {"model": s.ErrosSchema}, 409: {"model": s.ErrosSchema}},
)
async def assumir(
    loja_id: UUID, lead_id: UUID, corpo: s.AssumirIn, casos: Casos
) -> s.CardLeadSchema:
    return s.CardLeadSchema.de(await casos.assumir(loja_id, lead_id, corpo.vendedor_id))


@router.post(
    "/leads/{lead_id}/devolver",
    response_model=s.CardLeadSchema,
    summary="Devolve a conversa para a IA",
    responses={404: {"model": s.ErrosSchema}, 409: {"model": s.ErrosSchema}},
)
async def devolver(loja_id: UUID, lead_id: UUID, casos: Casos) -> s.CardLeadSchema:
    return s.CardLeadSchema.de(await casos.devolver(loja_id, lead_id))


@router.post(
    "/leads/{lead_id}/mensagens",
    status_code=201,
    response_model=s.EnvioMensagemSchema,
    summary="Envia uma mensagem como vendedor (exige ter assumido a conversa)",
    responses={404: {"model": s.ErrosSchema}, 409: {"model": s.ErrosSchema}},
)
async def enviar_mensagem(
    loja_id: UUID, lead_id: UUID, corpo: s.MensagemVendedorIn, casos: Casos
) -> s.EnvioMensagemSchema:
    return s.EnvioMensagemSchema.de(await casos.enviar_mensagem(loja_id, lead_id, corpo.texto))


@router.get(
    "/eventos",
    summary="Stream SSE de eventos da loja (EtapaMudou, MensagemNova, DonoMudou)",
    response_class=StreamingResponse,
    description=(
        "`text/event-stream`: cada `data:` e um JSON do schema `EventoPainel` "
        "(uniao discriminada por `evento`)."
    ),
)
async def eventos(
    loja_id: UUID,
    lojas: Lojas,
    barramento: Annotated[BarramentoMensagens, Depends(get_barramento)],
) -> StreamingResponse:
    await _exigir_loja(lojas, loja_id)
    return StreamingResponse(
        eventos_sse(barramento.assinar(topico_painel(loja_id))),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )
