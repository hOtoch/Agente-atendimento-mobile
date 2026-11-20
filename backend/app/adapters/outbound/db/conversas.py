"""Repositorio Postgres de leads, conversas e mensagens de entrada.

Cada metodo faz commit: o worker que atende a conversa roda em outro processo e precisa
enxergar o que foi gravado antes de ser agendado.
"""

import uuid
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.outbound.db.models import Conversa, Lead
from app.adapters.outbound.db.repositorios import MensagemRepositorio
from app.application.canal import Canal, MensagemEntrada, TipoMensagem


class RepositorioConversasSql:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._mensagens = MensagemRepositorio(session)

    async def obter_ou_criar(self, loja_id: UUID, canal: Canal, contato: str) -> tuple[UUID, UUID]:
        # Corrida entre duas primeiras mensagens: o ON CONFLICT evita violar `contato`.
        await self._session.execute(
            insert(Lead)
            .values(
                id=uuid.uuid4(),
                loja_id=loja_id,
                canal=canal.value,
                telefone=contato,
                etapa="novo_contato",
                dono="ia",
            )
            .on_conflict_do_nothing(index_elements=["loja_id", "canal", "telefone"])
        )
        lead_id = (
            await self._session.execute(
                select(Lead.id).where(
                    Lead.loja_id == loja_id, Lead.canal == canal.value, Lead.telefone == contato
                )
            )
        ).scalar_one()
        conversa_id = (
            await self._session.execute(
                select(Conversa.id)
                .where(Conversa.lead_id == lead_id)
                .order_by(Conversa.criado_em.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if conversa_id is None:
            conversa_id = uuid.uuid4()
            self._session.add(
                Conversa(id=conversa_id, loja_id=loja_id, lead_id=lead_id, canal=canal.value)
            )
        await self._session.commit()
        return lead_id, conversa_id

    async def registrar_entrada(self, conversa_id: UUID, msg: MensagemEntrada) -> bool:
        nova = await self._mensagens.inserir_se_nova(
            id=uuid.uuid4(),
            loja_id=msg.loja_id,
            conversa_id=conversa_id,
            canal=msg.canal.value,
            direcao="entrada",
            tipo=msg.tipo.value,
            conteudo=msg.texto,
            midia_url=msg.midia_url,
            id_externo=msg.id_externo,
        )
        await self._session.commit()
        return nova

    async def registrar_saida_vendedor(
        self,
        conversa_id: UUID,
        *,
        loja_id: UUID,
        canal: Canal,
        id_externo: str,
        tipo: TipoMensagem,
        texto: str | None,
        midia_url: str | None,
    ) -> bool:
        """Mensagem que o vendedor digitou fora do painel (ex.: celular da loja). Idempotente."""
        nova = await self._mensagens.inserir_se_nova(
            id=uuid.uuid4(),
            loja_id=loja_id,
            conversa_id=conversa_id,
            canal=canal.value,
            direcao="saida",
            autor="vendedor",
            tipo=tipo.value,
            conteudo=texto,
            midia_url=midia_url,
            id_externo=id_externo,
        )
        await self._session.commit()
        return nova

    async def definir_nome_se_vazio(
        self, loja_id: UUID, canal: Canal, contato: str, nome: str
    ) -> None:
        await self._session.execute(
            update(Lead)
            .where(
                Lead.loja_id == loja_id,
                Lead.canal == canal.value,
                Lead.telefone == contato,
                Lead.nome.is_(None),
            )
            .values(nome=nome[:200])
        )
        await self._session.commit()
