"""Repositorio Postgres de conversa/lead para o orquestrador e registro de eventos.

Cada metodo faz commit (o worker enxerga o que a API gravou e vice-versa).
"""

from __future__ import annotations

import uuid
from typing import Any
from uuid import UUID

from sqlalchemy import select, tuple_, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.outbound.db.models import Conversa, Evento, Lead, Mensagem
from app.adapters.outbound.db.repositorios import MensagemRepositorio
from app.application.agente.conversa_portas import ConversaLead, EntradaConversa
from app.application.agente.transcricao import CursorEntrada
from app.application.canal import Canal, MensagemSaida, TipoMensagem
from app.domain.kanban import Etapa


class RepositorioProcessamentoSql:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def obter_conversa(self, conversa_id: UUID) -> ConversaLead | None:
        linha = (
            await self._session.execute(
                select(
                    Conversa.loja_id,
                    Conversa.lead_id,
                    Lead.canal,
                    Lead.telefone,
                    Lead.etapa,
                    Lead.dono,
                )
                .join(Lead, Lead.id == Conversa.lead_id)
                .where(Conversa.id == conversa_id)
            )
        ).one_or_none()
        if linha is None:
            return None
        loja_id, lead_id, canal, contato, etapa, dono = linha
        return ConversaLead(
            conversa_id, loja_id, lead_id, Canal(canal), contato, Etapa(etapa), dono
        )

    async def entradas_novas(
        self, conversa_id: UUID, apos: CursorEntrada | None
    ) -> list[EntradaConversa]:
        consulta = select(
            Mensagem.id, Mensagem.criado_em, Mensagem.tipo, Mensagem.conteudo, Mensagem.midia_url
        ).where(Mensagem.conversa_id == conversa_id, Mensagem.direcao == "entrada")
        if apos is not None:
            consulta = consulta.where(
                tuple_(Mensagem.criado_em, Mensagem.id) > tuple_(apos.criado_em, apos.id)
            )
        linhas = (
            await self._session.execute(consulta.order_by(Mensagem.criado_em, Mensagem.id))
        ).all()
        # termina a transacao de leitura: o proximo SELECT enxerga o que outros gravarem
        await self._session.commit()
        return [EntradaConversa(i, ts, TipoMensagem(t), c, m) for i, ts, t, c, m in linhas]

    async def atualizar_etapa(self, lead_id: UUID, etapa: Etapa) -> None:
        await self._session.execute(
            update(Lead).where(Lead.id == lead_id).values(etapa=etapa.value)
        )
        await self._session.commit()

    async def registrar_saida(self, conversa_id: UUID, msg: MensagemSaida) -> None:
        await MensagemRepositorio(self._session).inserir_se_nova(
            id=uuid.uuid4(),
            loja_id=msg.loja_id,
            conversa_id=conversa_id,
            canal=msg.canal.value,
            direcao="saida",
            tipo=msg.tipo.value,
            conteudo=msg.texto,
            midia_url=msg.midia_url,
            id_externo=None,
        )
        await self._session.commit()


class RegistroEventosSql:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def registrar(
        self, loja_id: UUID, lead_id: UUID, tipo: str, payload: dict[str, Any]
    ) -> None:
        self._session.add(
            Evento(id=uuid.uuid4(), loja_id=loja_id, lead_id=lead_id, tipo=tipo, payload=payload)
        )
        await self._session.commit()
