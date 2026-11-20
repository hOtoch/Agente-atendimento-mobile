"""Transcricao do LLM no Postgres, na tabela `eventos` (sem migration).

`eventos` nao tem `conversa_id`; cada linha guarda `conversa_id` no payload e usa `lead_id`
(da conversa) como filtro de indice. Formato:

- `tipo="llm_mensagem"`, payload `{"conversa_id", "seq", "papel", "blocos", "bruto"}`: uma por
  `MensagemLLM`, em ordem de `seq` (1, 2, 3...). So INSERT, nunca UPDATE/DELETE.
- `tipo="llm_cursor"`, payload `{"conversa_id", "criado_em", "id"}`: ate onde as entradas do
  cliente (`mensagens`, direcao entrada) ja foram consumidas; vale a ultima por `criado_em`.

Consulta da transcricao: `lead_id = <lead da conversa> AND tipo = 'llm_mensagem' AND
payload->>'conversa_id' = <conversa> ORDER BY (payload->>'seq')::int`. JSONB nao preserva a
ordem das chaves dos objetos, mas todos os valores (assinaturas, thinking) voltam identicos.
Cada metodo faz commit (o worker roda em outro processo).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from uuid import UUID

from sqlalchemy import Integer, func, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.outbound.db.models import Conversa, Evento
from app.application.agente.transcricao import (
    CursorEntrada,
    desserializar_mensagem,
    serializar_mensagem,
)
from app.application.llm import MensagemLLM

TIPO_MENSAGEM = "llm_mensagem"
TIPO_CURSOR = "llm_cursor"


class ConversaNaoEncontrada(Exception):
    pass


class RepositorioTranscricaoSql:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _dono(self, conversa_id: UUID) -> tuple[UUID, UUID]:
        linha = (
            await self._session.execute(
                select(Conversa.loja_id, Conversa.lead_id).where(Conversa.id == conversa_id)
            )
        ).one_or_none()
        if linha is None:
            raise ConversaNaoEncontrada(str(conversa_id))
        return linha[0], linha[1]

    def _da_conversa(self, tipo: str, lead_id: UUID, conversa_id: UUID):  # type: ignore[no-untyped-def]
        return (
            Evento.lead_id == lead_id,
            Evento.tipo == tipo,
            Evento.payload["conversa_id"].astext == str(conversa_id),
        )

    async def listar(self, conversa_id: UUID) -> list[MensagemLLM]:
        _, lead_id = await self._dono(conversa_id)
        linhas = (
            (
                await self._session.execute(
                    select(Evento.payload)
                    .where(*self._da_conversa(TIPO_MENSAGEM, lead_id, conversa_id))
                    .order_by(Evento.payload["seq"].astext.cast(Integer))
                )
            )
            .scalars()
            .all()
        )
        return [desserializar_mensagem(p) for p in linhas]

    async def _gravar(
        self,
        conversa_id: UUID,
        mensagens: list[MensagemLLM],
        cursor: CursorEntrada | None,
    ) -> None:
        loja_id, lead_id = await self._dono(conversa_id)
        ultimo = (
            await self._session.execute(
                select(func.max(Evento.payload["seq"].astext.cast(Integer))).where(
                    *self._da_conversa(TIPO_MENSAGEM, lead_id, conversa_id)
                )
            )
        ).scalar_one()
        seq = int(ultimo or 0)
        linhas = []
        for msg in mensagens:
            seq += 1
            payload = {"conversa_id": str(conversa_id), "seq": seq, **serializar_mensagem(msg)}
            linhas.append(
                {
                    "id": uuid.uuid4(),
                    "loja_id": loja_id,
                    "lead_id": lead_id,
                    "tipo": TIPO_MENSAGEM,
                    "payload": payload,
                }
            )
        if cursor is not None:
            linhas.append(
                {
                    "id": uuid.uuid4(),
                    "loja_id": loja_id,
                    "lead_id": lead_id,
                    "tipo": TIPO_CURSOR,
                    "payload": {
                        "conversa_id": str(conversa_id),
                        "criado_em": cursor.criado_em.isoformat(),
                        "id": str(cursor.id),
                    },
                }
            )
        if linhas:
            await self._session.execute(insert(Evento), linhas)
        await self._session.commit()

    async def acrescentar(
        self,
        conversa_id: UUID,
        mensagens: list[MensagemLLM],
        consumido_ate: CursorEntrada | None = None,
    ) -> None:
        await self._gravar(conversa_id, mensagens, consumido_ate)

    async def marcar_consumidas(self, conversa_id: UUID, ate: CursorEntrada) -> None:
        await self._gravar(conversa_id, [], ate)

    async def consumido_ate(self, conversa_id: UUID) -> CursorEntrada | None:
        _, lead_id = await self._dono(conversa_id)
        payload = (
            await self._session.execute(
                select(Evento.payload)
                .where(*self._da_conversa(TIPO_CURSOR, lead_id, conversa_id))
                .order_by(Evento.criado_em.desc(), Evento.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if payload is None:
            return None
        return CursorEntrada(datetime.fromisoformat(payload["criado_em"]), UUID(payload["id"]))
