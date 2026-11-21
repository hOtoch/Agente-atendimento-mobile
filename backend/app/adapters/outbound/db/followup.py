"""Repositorios Postgres do follow-up: configuracao por loja, candidatos e tentativas.

Tentativa = evento `followup` (com `criado_em` explicito: o relogio e do chamador). Os
follow-ups "da rodada" sao os enviados DEPOIS da ultima mensagem do cliente.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.dialects.postgresql import distinct_on, insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.outbound.db.models import ConfigFollowupRow, Conversa, Evento, Lead, Mensagem
from app.application.canal import Canal
from app.application.followup import TIPO_EVENTO_FOLLOWUP, CandidatoFollowup
from app.domain.followup import ConfigFollowup
from app.domain.kanban import Etapa

_EPOCA = datetime(1970, 1, 1, tzinfo=UTC)


class RepositorioConfigFollowupSql:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def obter(self, loja_id: UUID) -> ConfigFollowup:
        row = await self._s.get(ConfigFollowupRow, loja_id, populate_existing=True)
        return ConfigFollowup.padrao() if row is None else _para_dominio(row)

    async def salvar(self, loja_id: UUID, config: ConfigFollowup) -> None:
        valores = {
            "ligado": config.ligado,
            "horas_por_etapa": {e.value: h for e, h in config.horas_por_etapa.items()},
            "max_tentativas": config.max_tentativas,
            "intervalo_horas": config.intervalo_horas,
            "hora_inicio": config.hora_inicio,
            "hora_fim": config.hora_fim,
            "max_dias_parado": config.max_dias_parado,
        }
        stmt = insert(ConfigFollowupRow).values(loja_id=loja_id, **valores)
        await self._s.execute(
            stmt.on_conflict_do_update(index_elements=[ConfigFollowupRow.loja_id], set_=valores)
        )

    async def lojas_com_followup_ligado(self) -> list[UUID]:
        linhas = await self._s.execute(
            select(ConfigFollowupRow.loja_id).where(ConfigFollowupRow.ligado.is_(True))
        )
        return list(linhas.scalars())


def _para_dominio(row: ConfigFollowupRow) -> ConfigFollowup:
    return ConfigFollowup(
        ligado=row.ligado,
        horas_por_etapa={Etapa(e): int(h) for e, h in row.horas_por_etapa.items()},
        max_tentativas=row.max_tentativas,
        intervalo_horas=row.intervalo_horas,
        hora_inicio=row.hora_inicio,
        hora_fim=row.hora_fim,
        max_dias_parado=row.max_dias_parado,
    )


class RepositorioFollowupSql:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def listar_candidatos(
        self, loja_id: UUID, etapas: list[Etapa], parado_antes_de: datetime
    ) -> list[CandidatoFollowup]:
        conversa = (
            select(Conversa.id.label("id"), Conversa.lead_id.label("lead_id"))
            .where(Conversa.loja_id == loja_id)
            .ext(distinct_on(Conversa.lead_id))
            .order_by(Conversa.lead_id, Conversa.criado_em.desc())
            .subquery()
        )
        ordem = (Mensagem.criado_em.desc(), Mensagem.id.desc())
        ultima_em = (
            select(Mensagem.criado_em)
            .where(Mensagem.conversa_id == conversa.c.id)
            .order_by(*ordem)
            .limit(1)
            .correlate(conversa)
            .scalar_subquery()
        )
        ultima_direcao = (
            select(Mensagem.direcao)
            .where(Mensagem.conversa_id == conversa.c.id)
            .order_by(*ordem)
            .limit(1)
            .correlate(conversa)
            .scalar_subquery()
        )
        ultima_do_cliente = (
            select(func.max(Mensagem.criado_em))
            .where(Mensagem.conversa_id == conversa.c.id, Mensagem.direcao == "entrada")
            .correlate(conversa)
            .scalar_subquery()
        )
        followups = and_(Evento.lead_id == Lead.id, Evento.tipo == TIPO_EVENTO_FOLLOWUP)
        tentativas = (
            select(func.count())
            .select_from(Evento)
            .where(followups, Evento.criado_em > func.coalesce(ultima_do_cliente, _EPOCA))
            .correlate(Lead, conversa)
            .scalar_subquery()
        )
        ultimo_followup = (
            select(func.max(Evento.criado_em)).where(followups).correlate(Lead).scalar_subquery()
        )
        consulta = (
            select(
                Lead.id,
                Lead.canal,
                Lead.telefone,
                Lead.etapa,
                Lead.dono,
                conversa.c.id,
                ultima_em.label("ultima_em"),
                ultima_direcao.label("ultima_direcao"),
                tentativas.label("tentativas"),
                ultimo_followup.label("ultimo_followup"),
            )
            .join(conversa, conversa.c.lead_id == Lead.id)
            .where(Lead.loja_id == loja_id, Lead.etapa.in_([e.value for e in etapas]))
            .where(ultima_em < parado_antes_de)
            .order_by(ultima_em)
        )
        linhas = (await self._s.execute(consulta)).all()
        # termina a transacao de leitura: a proxima consulta enxerga o que outros gravarem
        await self._s.commit()
        return [
            CandidatoFollowup(
                loja_id=loja_id,
                lead_id=lead_id,
                conversa_id=conversa_id,
                canal=Canal(canal),
                contato=telefone,
                etapa=Etapa(etapa),
                dono=dono,
                ultima_mensagem_em=ultima,
                ultima_mensagem_do_cliente=direcao == "entrada",
                tentativas=int(n),
                ultimo_followup_em=ultimo,
            )
            for lead_id, canal, telefone, etapa, dono, conversa_id, ultima, direcao, n, ultimo
            in linhas
        ]  # fmt: skip


class RegistroTentativasSql:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def registrar(
        self, loja_id: UUID, lead_id: UUID, *, tentativa: int, etapa: Etapa, em: datetime
    ) -> None:
        self._s.add(
            Evento(
                id=uuid.uuid4(),
                loja_id=loja_id,
                lead_id=lead_id,
                tipo=TIPO_EVENTO_FOLLOWUP,
                payload={"tentativa": tentativa, "etapa": etapa.value},
                criado_em=em,
            )
        )
        await self._s.commit()
