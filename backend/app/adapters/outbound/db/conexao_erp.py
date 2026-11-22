"""Repositorio Postgres da conexao da loja com o ERP (uma linha por loja)."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.outbound.db.models import ConexaoErpRow
from app.domain.conexao_erp import ConexaoErp


class RepositorioConexaoErpSql:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def obter(self, loja_id: UUID) -> ConexaoErp | None:
        row = await self._s.get(ConexaoErpRow, loja_id, populate_existing=True)
        return None if row is None else _para_dominio(row)

    async def salvar(self, conexao: ConexaoErp) -> None:
        valores = {
            "provedor": conexao.provedor,
            "system_unit_id": conexao.system_unit_id,
            "filtro_loja": conexao.filtro_loja,
            "ativo": conexao.ativo,
            "intervalo_min": conexao.intervalo_min,
            "exportar_handoff": conexao.exportar_handoff,
        }
        stmt = insert(ConexaoErpRow).values(loja_id=conexao.loja_id, **valores)
        await self._s.execute(
            stmt.on_conflict_do_update(index_elements=[ConexaoErpRow.loja_id], set_=valores)
        )

    async def registrar_sincronizacao(
        self, loja_id: UUID, *, em: datetime, status: str, relatorio: Mapping[str, Any] | None
    ) -> None:
        await self._s.execute(
            update(ConexaoErpRow)
            .where(ConexaoErpRow.loja_id == loja_id)
            .values(
                ultima_sincronizacao_em=em,
                ultimo_status=status,
                ultimo_relatorio=None if relatorio is None else dict(relatorio),
            )
        )

    async def listar_ativas(self) -> list[ConexaoErp]:
        linhas = await self._s.execute(
            select(ConexaoErpRow)
            .where(ConexaoErpRow.ativo.is_(True))
            .order_by(ConexaoErpRow.loja_id)
            .execution_options(populate_existing=True)
        )
        return [_para_dominio(r) for r in linhas.scalars()]


def _para_dominio(row: ConexaoErpRow) -> ConexaoErp:
    return ConexaoErp(
        loja_id=row.loja_id,
        provedor=row.provedor,
        system_unit_id=row.system_unit_id,
        filtro_loja=row.filtro_loja,
        ativo=row.ativo,
        intervalo_min=row.intervalo_min,
        exportar_handoff=row.exportar_handoff,
        ultima_sincronizacao_em=row.ultima_sincronizacao_em,
        ultimo_status=row.ultimo_status,
        ultimo_relatorio=row.ultimo_relatorio,
    )
