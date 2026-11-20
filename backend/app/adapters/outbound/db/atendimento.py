"""Repositorio Postgres do estado do atendimento: uma linha de `fichas` por versao.

Cada `salvar` insere versao+1 (historico preservado) e faz commit, como os demais repositorios
chamados pelo worker. A fila serializa as mensagens de uma conversa, entao nao ha corrida;
se houvesse, a unique (lead_id, versao) rejeitaria a segunda gravacao.
"""

from __future__ import annotations

import uuid
from uuid import UUID

from sqlalchemy import func, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.outbound.db.models import Ficha as FichaRow
from app.application.agente.estado import EstadoAtendimento


class RepositorioAtendimentoSql:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def obter(self, loja_id: UUID, lead_id: UUID) -> EstadoAtendimento:
        dados = (
            await self._session.execute(
                select(FichaRow.dados)
                .where(FichaRow.loja_id == loja_id, FichaRow.lead_id == lead_id)
                .order_by(FichaRow.versao.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        return EstadoAtendimento() if dados is None else EstadoAtendimento.de_dict(dados)

    async def salvar(self, loja_id: UUID, lead_id: UUID, estado: EstadoAtendimento) -> int:
        proxima = (
            select(func.coalesce(func.max(FichaRow.versao), 0) + 1)
            .where(FichaRow.lead_id == lead_id)
            .scalar_subquery()
        )
        versao = (
            await self._session.execute(
                insert(FichaRow)
                .values(
                    id=uuid.uuid4(),
                    loja_id=loja_id,
                    lead_id=lead_id,
                    versao=proxima,
                    dados=estado.para_dict(),
                )
                .returning(FichaRow.versao)
            )
        ).scalar_one()
        await self._session.commit()
        return int(versao)
