"""Pausa provisoria da IA quando o vendedor fala direto no celular da loja (`fromMe`).

Implementa `PausarIA` (porta em `application/whatsapp.py`) so com o repositorio e o
publicador do painel: `dono = vendedor` sem vendedor atribuido. O handoff completo (atribuir
quem assumiu, evento de auditoria rico, resumo) e do `application/handoff.py`.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID

from app.application.painel.eventos import EventoDonoMudou
from app.application.painel.portas import DONO_VENDEDOR, RepositorioPainel
from app.application.painel.publicador import PublicadorPainel, publicar_sem_falhar

ORIGEM_CELULAR_DA_LOJA = "celular_da_loja"


def _agora() -> datetime:
    return datetime.now(UTC)


class PausarIAProvisorio:
    def __init__(
        self,
        repo: RepositorioPainel,
        publicador: PublicadorPainel,
        agora: Callable[[], datetime] = _agora,
    ) -> None:
        self._repo = repo
        self._publicador = publicador
        self._agora = agora

    async def pausar_por_vendedor(self, loja_id: UUID, lead_id: UUID) -> None:
        lead = await self._repo.obter_lead(loja_id, lead_id)
        if lead is None or lead.dono == DONO_VENDEDOR:
            return  # sem lead ou ja pausada: nada a fazer (e nada a publicar)
        dono = DONO_VENDEDOR if lead.vendedor_id is None else f"{DONO_VENDEDOR}:{lead.vendedor_id}"
        # vendedor_id None preserva a atribuicao existente (se houver).
        await self._repo.definir_dono(
            loja_id,
            lead_id,
            DONO_VENDEDOR,
            None,
            {"dono": dono, "origem": ORIGEM_CELULAR_DA_LOJA},
        )
        await publicar_sem_falhar(
            self._publicador,
            loja_id,
            EventoDonoMudou(
                lead_id=lead_id, dono=dono, vendedor_id=lead.vendedor_id, em=self._agora()
            ),
        )
