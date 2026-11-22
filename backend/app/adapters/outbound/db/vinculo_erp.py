"""Ids do lead no ERP (`leads.erp_cliente_id`, `leads.erp_orcamento_id`) em Postgres."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.outbound.db.models import Lead
from app.application.pedido_erp import VinculoErp


class VinculosErpLeadSql:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def obter(self, loja_id: UUID, lead_id: UUID) -> VinculoErp:
        linha = (
            await self._s.execute(
                select(Lead.erp_cliente_id, Lead.erp_orcamento_id)
                .where(Lead.id == lead_id, Lead.loja_id == loja_id)
                .execution_options(populate_existing=True)
            )
        ).one_or_none()
        return VinculoErp() if linha is None else VinculoErp(linha[0], linha[1])

    async def gravar(
        self,
        loja_id: UUID,
        lead_id: UUID,
        *,
        cliente_id: int | None = None,
        orcamento_id: int | None = None,
    ) -> None:
        valores: dict[str, int] = {}
        if cliente_id is not None:
            valores["erp_cliente_id"] = cliente_id
        if orcamento_id is not None:
            valores["erp_orcamento_id"] = orcamento_id
        if not valores:
            return
        await self._s.execute(
            update(Lead).where(Lead.id == lead_id, Lead.loja_id == loja_id).values(**valores)
        )
