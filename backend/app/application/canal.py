"""Canais de mensagem: portas e caso de uso de recebimento.

A entrada so persiste e agenda; quem responde e um worker em outro processo, e a saida
volta ao cliente pelo `BarramentoMensagens` (Redis pub/sub em producao).
"""

from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from app.application.painel.eventos import EventoMensagemNova
from app.application.painel.publicador import (
    PublicadorPainel,
    PublicadorPainelNulo,
    publicar_sem_falhar,
)


class Canal(StrEnum):
    WEBCHAT = "webchat"
    WHATSAPP = "whatsapp"
    INSTAGRAM = "instagram"


class TipoMensagem(StrEnum):
    """Valores batem com o CHECK de `mensagens.tipo`."""

    TEXTO = "texto"
    AUDIO = "audio"
    IMAGEM = "imagem"


@dataclass(frozen=True, slots=True)
class MensagemEntrada:
    loja_id: UUID
    canal: Canal
    id_externo: str
    remetente: str
    """Id do contato no canal (no webchat, o id da sessao)."""
    tipo: TipoMensagem
    texto: str | None
    midia_url: str | None
    recebida_em: datetime


@dataclass(frozen=True, slots=True)
class MensagemSaida:
    loja_id: UUID
    canal: Canal
    destinatario: str
    tipo: TipoMensagem
    texto: str | None
    midia_url: str | None


class CanalPort(Protocol):
    async def enviar(self, msg: MensagemSaida) -> None: ...


class BarramentoMensagens(Protocol):
    async def publicar(self, topico: str, payload: dict[str, object]) -> None: ...

    def assinar(self, topico: str) -> AsyncIterator[dict[str, object]]: ...


class RepositorioConversas(Protocol):
    async def obter_ou_criar(self, loja_id: UUID, canal: Canal, contato: str) -> tuple[UUID, UUID]:
        """Devolve `(lead_id, conversa_id)`, criando o que faltar."""
        ...

    async def registrar_entrada(self, conversa_id: UUID, msg: MensagemEntrada) -> bool:
        """Idempotente por (canal, id_externo): False se a mensagem ja existia."""
        ...


class ReceberMensagem:
    def __init__(
        self,
        repo: RepositorioConversas,
        agendar: Callable[[UUID], Awaitable[None]],
        painel: PublicadorPainel | None = None,
    ) -> None:
        self._repo = repo
        self._agendar = agendar
        self._painel = painel or PublicadorPainelNulo()

    async def __call__(self, msg: MensagemEntrada) -> tuple[UUID, bool]:
        lead_id, conversa_id = await self._repo.obter_ou_criar(
            msg.loja_id, msg.canal, msg.remetente
        )
        nova = await self._repo.registrar_entrada(conversa_id, msg)
        if nova:
            await self._agendar(conversa_id)
            await publicar_sem_falhar(
                self._painel,
                msg.loja_id,
                EventoMensagemNova(
                    lead_id=lead_id,
                    conversa_id=conversa_id,
                    autor="cliente",
                    direcao="entrada",
                    tipo=msg.tipo.value,
                    texto=msg.texto,
                    midia_url=msg.midia_url,
                    em=msg.recebida_em,
                ),
            )
        return conversa_id, nova
