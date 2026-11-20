"""Publicador do painel sobre o barramento: um topico por loja (`painel:<loja_id>`)."""

from __future__ import annotations

from uuid import UUID

from app.application.canal import BarramentoMensagens
from app.application.painel.eventos import EventoPainel


def topico_painel(loja_id: UUID) -> str:
    return f"painel:{loja_id}"


class PublicadorPainelBarramento:
    """Implementa `PublicadorPainel`."""

    def __init__(self, barramento: BarramentoMensagens) -> None:
        self._barramento = barramento

    async def publicar(self, loja_id: UUID, evento: EventoPainel) -> None:
        await self._barramento.publicar(topico_painel(loja_id), evento.para_dict())
