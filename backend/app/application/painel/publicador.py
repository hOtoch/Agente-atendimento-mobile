"""Porta de publicacao de eventos do painel (separada para o canal e o agente a usarem)."""

from __future__ import annotations

import logging
from typing import Protocol
from uuid import UUID

from app.application.painel.eventos import EventoPainel

log = logging.getLogger(__name__)


class PublicadorPainel(Protocol):
    async def publicar(self, loja_id: UUID, evento: EventoPainel) -> None: ...


class PublicadorPainelNulo:
    """Descarta os eventos (padrao quando ninguem escuta)."""

    async def publicar(self, loja_id: UUID, evento: EventoPainel) -> None:
        return None


async def publicar_sem_falhar(
    publicador: PublicadorPainel, loja_id: UUID, evento: EventoPainel
) -> None:
    """O estado ja foi gravado: falha no tempo real so vira log, nunca derruba o atendimento."""
    try:
        await publicador.publicar(loja_id, evento)
    except Exception:
        log.exception("falha ao publicar %s no painel da loja %s", evento.nome, loja_id)
