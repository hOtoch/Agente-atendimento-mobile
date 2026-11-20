"""WhatsApp da loja: status da conexao e QR (onboarding) e webhook da Evolution."""

from __future__ import annotations

import logging
import secrets
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query
from pydantic import BaseModel

from app.adapters.inbound.evolution.normalizar import Ignorado, normalizar
from app.application.config.modelos import LojaNaoEncontrada
from app.application.config.portas import RepositorioLojas
from app.application.whatsapp import (
    ConectarWhatsApp,
    EstadoConexao,
    ProcessarMensagemWhatsApp,
    ResultadoWebhook,
    WhatsAppGateway,
)
from app.infra.dependencias import (
    get_lojas,
    get_processar_whatsapp,
    get_whatsapp_gateway,
)
from app.infra.settings import Settings, get_settings

log = logging.getLogger(__name__)

router = APIRouter(tags=["whatsapp"])


class StatusWhatsAppSchema(BaseModel):
    status: EstadoConexao


class ConexaoWhatsAppSchema(BaseModel):
    status: EstadoConexao
    qr_base64: str | None
    """Imagem do QR (`data:image/png;base64,...`); None se ja conectado ou ainda gerando."""


class ResultadoWebhookSchema(BaseModel):
    resultado: ResultadoWebhook


async def _exigir_loja(lojas: RepositorioLojas, loja_id: UUID) -> None:
    if not await lojas.existe(loja_id):
        raise LojaNaoEncontrada(loja_id)


@router.get(
    "/lojas/{loja_id}/whatsapp/status",
    response_model=StatusWhatsAppSchema,
    summary="Estado da conexao do WhatsApp da loja",
    responses={
        404: {"description": "Loja nao encontrada."},
        502: {"description": "Evolution fora."},
    },
)
async def status_whatsapp(
    loja_id: UUID,
    lojas: Annotated[RepositorioLojas, Depends(get_lojas)],
    gateway: Annotated[WhatsAppGateway, Depends(get_whatsapp_gateway)],
) -> StatusWhatsAppSchema:
    await _exigir_loja(lojas, loja_id)
    return StatusWhatsAppSchema(status=await gateway.status_conexao(loja_id))


@router.post(
    "/lojas/{loja_id}/whatsapp/conectar",
    response_model=ConexaoWhatsAppSchema,
    summary="Cria a instancia (se preciso) e devolve o QR para conectar o numero",
    responses={
        404: {"description": "Loja nao encontrada."},
        502: {"description": "Evolution fora."},
    },
)
async def conectar_whatsapp(
    loja_id: UUID,
    lojas: Annotated[RepositorioLojas, Depends(get_lojas)],
    gateway: Annotated[WhatsAppGateway, Depends(get_whatsapp_gateway)],
) -> ConexaoWhatsAppSchema:
    await _exigir_loja(lojas, loja_id)
    qr = await ConectarWhatsApp(gateway)(loja_id)
    return ConexaoWhatsAppSchema(status=qr.status, qr_base64=qr.qr_base64)


def _autorizar(
    settings: Annotated[Settings, Depends(get_settings)],
    x_webhook_token: Annotated[str | None, Header()] = None,
    token: Annotated[str | None, Query()] = None,
) -> None:
    recebido = x_webhook_token or token or ""
    if not secrets.compare_digest(recebido.encode(), settings.evolution_webhook_token.encode()):
        raise HTTPException(status_code=401, detail="token do webhook invalido")


@router.post(
    "/webhooks/evolution",
    response_model=ResultadoWebhookSchema,
    include_in_schema=False,
    dependencies=[Depends(_autorizar)],
)
async def webhook_evolution(
    payload: Annotated[Any, Body()],
    processar: Annotated[ProcessarMensagemWhatsApp, Depends(get_processar_whatsapp)],
    lojas: Annotated[RepositorioLojas, Depends(get_lojas)],
) -> ResultadoWebhookSchema:
    """Responde 200 a tudo que nao for erro de autenticacao: a Evolution nao deve reenviar."""
    evento = normalizar(payload)
    if isinstance(evento, Ignorado):
        log.debug("webhook da Evolution ignorado: %s", evento.motivo)
        return ResultadoWebhookSchema(resultado=ResultadoWebhook.IGNORADA)
    if not await lojas.existe(evento.loja_id):
        log.warning("webhook da Evolution para loja inexistente %s", evento.loja_id)
        return ResultadoWebhookSchema(resultado=ResultadoWebhook.IGNORADA)
    return ResultadoWebhookSchema(resultado=await processar(evento))
