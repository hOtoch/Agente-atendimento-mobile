"""Repositorio Postgres do painel.

Cada gravacao e uma transacao (lead + evento de auditoria) e termina em commit: o evento em
tempo real so e publicado depois, pelo caso de uso.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Select, delete, func, select, update
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.outbound.db.models import Conversa, Evento, Lead, Mensagem, Vendedor
from app.adapters.outbound.db.models import Ficha as FichaRow
from app.application.agente.estado import EstadoAtendimento
from app.application.canal import Canal, TipoMensagem
from app.application.painel.portas import (
    AUTOR_VENDEDOR,
    EventoRegistro,
    LeadRegistro,
    MensagemRegistro,
)
from app.domain.kanban import Etapa

LIMITE_EVENTOS = 200


class RepositorioPainelSql:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def _consulta_leads(self, loja_id: UUID) -> Select[Any]:
        ficha = (
            select(FichaRow.lead_id, FichaRow.dados)
            .where(FichaRow.loja_id == loja_id)
            .ext(distinct_on(FichaRow.lead_id))
            .order_by(FichaRow.lead_id, FichaRow.versao.desc())
            .subquery()
        )
        etapa = (
            select(Evento.lead_id, func.max(Evento.criado_em).label("em"))
            .where(Evento.loja_id == loja_id, Evento.tipo == "etapa_mudou")
            .group_by(Evento.lead_id)
            .subquery()
        )
        conversa = (
            select(Conversa.lead_id, Conversa.id)
            .where(Conversa.loja_id == loja_id)
            .ext(distinct_on(Conversa.lead_id))
            .order_by(Conversa.lead_id, Conversa.criado_em.desc())
            .subquery()
        )
        return (
            select(
                Lead,
                Vendedor.nome,
                ficha.c.dados,
                etapa.c.em,
                conversa.c.id,
            )
            .outerjoin(Vendedor, Vendedor.id == Lead.vendedor_id)
            .outerjoin(ficha, ficha.c.lead_id == Lead.id)
            .outerjoin(etapa, etapa.c.lead_id == Lead.id)
            .outerjoin(conversa, conversa.c.lead_id == Lead.id)
            .where(Lead.loja_id == loja_id)
        )

    @staticmethod
    def _registro(linha: Any) -> LeadRegistro:
        lead, vendedor_nome, dados, etapa_em, conversa_id = linha
        return LeadRegistro(
            id=lead.id,
            loja_id=lead.loja_id,
            conversa_id=conversa_id,
            nome=lead.nome,
            telefone=lead.telefone,
            canal=Canal(lead.canal),
            etapa=Etapa(lead.etapa),
            etapa_desde=etapa_em or lead.criado_em,
            dono=lead.dono,
            vendedor_id=lead.vendedor_id,
            vendedor_nome=vendedor_nome,
            criado_em=lead.criado_em,
            estado=EstadoAtendimento() if dados is None else EstadoAtendimento.de_dict(dados),
        )

    async def listar_leads(self, loja_id: UUID) -> list[LeadRegistro]:
        linhas = (
            await self._session.execute(self._consulta_leads(loja_id).order_by(Lead.criado_em))
        ).all()
        return [self._registro(linha) for linha in linhas]

    async def obter_lead(self, loja_id: UUID, lead_id: UUID) -> LeadRegistro | None:
        linha = (
            await self._session.execute(self._consulta_leads(loja_id).where(Lead.id == lead_id))
        ).one_or_none()
        return None if linha is None else self._registro(linha)

    async def listar_mensagens(self, loja_id: UUID, lead_id: UUID) -> list[MensagemRegistro]:
        linhas = (
            await self._session.execute(
                select(Mensagem)
                .join(Conversa, Conversa.id == Mensagem.conversa_id)
                .where(Conversa.lead_id == lead_id, Mensagem.loja_id == loja_id)
                .order_by(Mensagem.criado_em, Mensagem.id)
            )
        ).scalars()
        return [_mensagem(m) for m in linhas]

    async def listar_eventos(self, loja_id: UUID, lead_id: UUID) -> list[EventoRegistro]:
        linhas = (
            await self._session.execute(
                select(Evento)
                .where(Evento.loja_id == loja_id, Evento.lead_id == lead_id)
                .order_by(Evento.criado_em.desc(), Evento.id)
                .limit(LIMITE_EVENTOS)
            )
        ).scalars()
        return [
            EventoRegistro(e.id, e.tipo, e.payload, e.criado_em) for e in reversed(list(linhas))
        ]

    async def vendedor_existe(self, loja_id: UUID, vendedor_id: UUID) -> bool:
        achado = await self._session.execute(
            select(Vendedor.id).where(Vendedor.id == vendedor_id, Vendedor.loja_id == loja_id)
        )
        return achado.scalar_one_or_none() is not None

    async def mover_etapa(
        self, loja_id: UUID, lead_id: UUID, etapa: Etapa, payload_evento: dict[str, Any]
    ) -> None:
        await self._session.execute(
            update(Lead)
            .where(Lead.id == lead_id, Lead.loja_id == loja_id)
            .values(etapa=etapa.value)
        )
        self._evento(loja_id, lead_id, "etapa_mudou", payload_evento)
        await self._session.commit()

    async def definir_dono(
        self,
        loja_id: UUID,
        lead_id: UUID,
        dono: str,
        vendedor_id: UUID | None,
        payload_evento: dict[str, Any],
        *,
        limpar_vendedor: bool = False,
    ) -> None:
        valores: dict[str, Any] = {"dono": dono}
        if vendedor_id is not None:
            valores["vendedor_id"] = vendedor_id
        elif limpar_vendedor:
            valores["vendedor_id"] = None
        await self._session.execute(
            update(Lead).where(Lead.id == lead_id, Lead.loja_id == loja_id).values(**valores)
        )
        self._evento(loja_id, lead_id, "dono_mudou", payload_evento)
        await self._session.commit()

    async def registrar_evento(
        self, loja_id: UUID, lead_id: UUID, tipo: str, payload: dict[str, Any]
    ) -> None:
        self._evento(loja_id, lead_id, tipo, payload)
        await self._session.commit()

    async def ultimo_evento(self, loja_id: UUID, lead_id: UUID, tipo: str) -> EventoRegistro | None:
        e = (
            await self._session.execute(
                select(Evento)
                .where(Evento.loja_id == loja_id, Evento.lead_id == lead_id, Evento.tipo == tipo)
                .order_by(Evento.criado_em.desc(), Evento.id)
                .limit(1)
            )
        ).scalar_one_or_none()
        return None if e is None else EventoRegistro(e.id, e.tipo, e.payload, e.criado_em)

    async def registrar_mensagem_vendedor(
        self, loja_id: UUID, conversa_id: UUID, canal: Canal, texto: str
    ) -> MensagemRegistro:
        mensagem = Mensagem(
            id=uuid.uuid4(),
            loja_id=loja_id,
            conversa_id=conversa_id,
            canal=canal.value,
            direcao="saida",
            autor=AUTOR_VENDEDOR,
            tipo="texto",
            conteudo=texto,
            criado_em=datetime.now(UTC),
        )
        registro = _mensagem(mensagem)  # antes do commit: nada de reload lazy no async
        self._session.add(mensagem)
        await self._session.commit()
        return registro

    async def apagar_lead(self, loja_id: UUID, lead_id: UUID) -> bool:
        # As FKs fazem o resto: conversas, mensagens e fichas em CASCADE; eventos em SET NULL.
        apagados = await self._session.execute(
            delete(Lead).where(Lead.id == lead_id, Lead.loja_id == loja_id).returning(Lead.id)
        )
        removido = apagados.scalar_one_or_none() is not None
        await self._session.commit()
        return removido

    def _evento(self, loja_id: UUID, lead_id: UUID, tipo: str, payload: dict[str, Any]) -> None:
        self._session.add(
            Evento(id=uuid.uuid4(), loja_id=loja_id, lead_id=lead_id, tipo=tipo, payload=payload)
        )


def _mensagem(m: Mensagem) -> MensagemRegistro:
    return MensagemRegistro(
        id=m.id,
        conversa_id=m.conversa_id,
        direcao=m.direcao,
        autor=m.autor,
        tipo=TipoMensagem(m.tipo),
        texto=m.conteudo,
        midia_url=m.midia_url,
        criada_em=m.criado_em,
        transcricao=m.transcricao,
    )
