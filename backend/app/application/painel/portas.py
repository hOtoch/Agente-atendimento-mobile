"""Porta de leitura/gravacao do painel (a publicacao de eventos fica em `publicador.py`)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from app.application.agente.estado import EstadoAtendimento
from app.application.canal import Canal, TipoMensagem
from app.domain.kanban import Etapa

DONO_IA = "ia"
DONO_VENDEDOR = "vendedor"
AUTOR_CLIENTE = "cliente"
AUTOR_IA = "ia"
AUTOR_VENDEDOR = "vendedor"


@dataclass(frozen=True, slots=True)
class LeadRegistro:
    id: UUID
    loja_id: UUID
    conversa_id: UUID | None
    nome: str | None
    telefone: str
    canal: Canal
    etapa: Etapa
    etapa_desde: datetime
    dono: str
    """`ia` ou `vendedor` (quem responde)."""
    vendedor_id: UUID | None
    """Vendedor atribuido ao lead (persiste mesmo quando o dono volta a ser a IA)."""
    vendedor_nome: str | None
    criado_em: datetime
    estado: EstadoAtendimento


@dataclass(frozen=True, slots=True)
class MensagemRegistro:
    id: UUID
    conversa_id: UUID
    direcao: str
    autor: str
    tipo: TipoMensagem
    texto: str | None
    midia_url: str | None
    criada_em: datetime


@dataclass(frozen=True, slots=True)
class EventoRegistro:
    id: UUID
    tipo: str
    payload: dict[str, Any]
    criado_em: datetime


class RepositorioPainel(Protocol):
    """Cada gravacao e atomica (lead + evento) e ja vem commitada."""

    async def listar_leads(self, loja_id: UUID) -> list[LeadRegistro]: ...

    async def obter_lead(self, loja_id: UUID, lead_id: UUID) -> LeadRegistro | None: ...

    async def listar_mensagens(self, loja_id: UUID, lead_id: UUID) -> list[MensagemRegistro]:
        """Todas as mensagens das conversas do lead, da mais antiga para a mais nova."""
        ...

    async def listar_eventos(self, loja_id: UUID, lead_id: UUID) -> list[EventoRegistro]:
        """Eventos de auditoria do lead, do mais antigo para o mais novo."""
        ...

    async def vendedor_existe(self, loja_id: UUID, vendedor_id: UUID) -> bool: ...

    async def mover_etapa(
        self, loja_id: UUID, lead_id: UUID, etapa: Etapa, payload_evento: dict[str, Any]
    ) -> None:
        """Grava a etapa e o evento `etapa_mudou`."""
        ...

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
        """Grava o dono e o evento `dono_mudou`.

        `vendedor_id` None preserva a atribuicao, a menos que `limpar_vendedor` (conversa
        aguardando vendedor: nenhum vendedor atribuido ainda).
        """
        ...

    async def registrar_evento(
        self, loja_id: UUID, lead_id: UUID, tipo: str, payload: dict[str, Any]
    ) -> None:
        """Grava um evento de auditoria do lead (ex.: `handoff_resumo`)."""
        ...

    async def ultimo_evento(self, loja_id: UUID, lead_id: UUID, tipo: str) -> EventoRegistro | None:
        """Evento mais recente do tipo, ou None."""
        ...

    async def registrar_mensagem_vendedor(
        self, loja_id: UUID, conversa_id: UUID, canal: Canal, texto: str
    ) -> MensagemRegistro: ...
