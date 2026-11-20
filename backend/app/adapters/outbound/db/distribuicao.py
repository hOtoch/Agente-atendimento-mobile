"""Atribuicao de vendedor a leads em SQL (porta `AtribuicoesLead`)."""

from __future__ import annotations

import uuid
from collections.abc import Mapping

from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.outbound.db.models import Lead
from app.application.distribuir_lead import LeadNaoEncontrado


class AtribuicoesLeadSql:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def travar_loja(self, loja_id: uuid.UUID) -> None:
        # trava de transacao por loja: liberada no commit/rollback; lojas nao se bloqueiam
        await self._s.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:chave, 0))"),
            {"chave": f"distribuicao-leads:{loja_id}"},
        )

    async def vendedor_atribuido(self, loja_id: uuid.UUID, lead_id: uuid.UUID) -> uuid.UUID | None:
        row = (
            await self._s.execute(
                select(Lead.vendedor_id)
                .where(Lead.id == lead_id, Lead.loja_id == loja_id)
                .execution_options(populate_existing=True)
            )
        ).one_or_none()
        if row is None:
            raise LeadNaoEncontrado(lead_id)
        return row[0]

    async def contar_por_vendedor(self, loja_id: uuid.UUID) -> Mapping[uuid.UUID, int]:
        rows = await self._s.execute(
            select(Lead.vendedor_id, func.count())
            .where(Lead.loja_id == loja_id, Lead.vendedor_id.is_not(None))
            .group_by(Lead.vendedor_id)
        )
        return {vendedor: n for vendedor, n in rows if vendedor is not None}

    async def atribuir(
        self, loja_id: uuid.UUID, lead_id: uuid.UUID, vendedor_id: uuid.UUID
    ) -> None:
        resultado = await self._s.execute(
            update(Lead)
            .where(Lead.id == lead_id, Lead.loja_id == loja_id)
            .values(vendedor_id=vendedor_id)
            .execution_options(synchronize_session="fetch")
        )
        if resultado.rowcount == 0:  # type: ignore[attr-defined]
            raise LeadNaoEncontrado(lead_id)
