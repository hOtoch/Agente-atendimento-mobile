"""Portas de leitura/escrita da conversa usadas pelo orquestrador, e versoes em memoria."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import UUID, uuid4

from app.application.agente.transcricao import CursorEntrada
from app.application.canal import Canal, MensagemSaida, TipoMensagem
from app.domain.kanban import Etapa

DONO_IA = "ia"
DONO_VENDEDOR = "vendedor"


@dataclass(frozen=True, slots=True)
class ConversaLead:
    conversa_id: UUID
    loja_id: UUID
    lead_id: UUID
    canal: Canal
    contato: str
    etapa: Etapa
    dono: str


@dataclass(frozen=True, slots=True)
class EntradaConversa:
    """Mensagem do cliente ainda nao respondida."""

    id: UUID
    criado_em: datetime
    tipo: TipoMensagem
    texto: str | None
    midia_url: str | None

    @property
    def cursor(self) -> CursorEntrada:
        return CursorEntrada(self.criado_em, self.id)


class RepositorioProcessamento(Protocol):
    async def obter_conversa(self, conversa_id: UUID) -> ConversaLead | None: ...

    async def entradas_novas(
        self, conversa_id: UUID, apos: CursorEntrada | None
    ) -> list[EntradaConversa]:
        """Entradas do cliente depois do cursor, em ordem de chegada."""
        ...

    async def atualizar_etapa(self, lead_id: UUID, etapa: Etapa) -> None: ...

    async def registrar_saida(self, conversa_id: UUID, msg: MensagemSaida) -> None: ...


class RegistroEventos(Protocol):
    async def registrar(
        self, loja_id: UUID, lead_id: UUID, tipo: str, payload: dict[str, Any]
    ) -> None: ...


# --- em memoria -------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class EventoRegistrado:
    loja_id: UUID
    lead_id: UUID
    tipo: str
    payload: dict[str, Any]


class EventosEmMemoria:
    def __init__(self) -> None:
        self.registrados: list[EventoRegistrado] = []

    async def registrar(
        self, loja_id: UUID, lead_id: UUID, tipo: str, payload: dict[str, Any]
    ) -> None:
        self.registrados.append(EventoRegistrado(loja_id, lead_id, tipo, payload))


@dataclass(slots=True)
class _Lead:
    loja_id: UUID
    canal: Canal
    contato: str
    etapa: Etapa
    dono: str


@dataclass(slots=True)
class _Conversa:
    lead_id: UUID
    entradas: list[EntradaConversa] = field(default_factory=list)


class ConversasEmMemoria:
    """Implementa `RepositorioProcessamento`; `adicionar_entrada` simula o cliente falando."""

    def __init__(self) -> None:
        self._leads: dict[UUID, _Lead] = {}
        self._conversas: dict[UUID, _Conversa] = {}
        self._relogio = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)
        self.saidas: list[tuple[UUID, MensagemSaida]] = []

    def criar_conversa(
        self,
        *,
        loja_id: UUID,
        lead_id: UUID,
        canal: Canal,
        contato: str,
        etapa: Etapa = Etapa.NOVO_CONTATO,
        dono: str = DONO_IA,
    ) -> UUID:
        self._leads[lead_id] = _Lead(loja_id, canal, contato, etapa, dono)
        conversa_id = uuid4()
        self._conversas[conversa_id] = _Conversa(lead_id)
        return conversa_id

    def adicionar_entrada(
        self,
        conversa_id: UUID,
        texto: str | None,
        *,
        tipo: str = "texto",
        midia_url: str | None = None,
    ) -> EntradaConversa:
        self._relogio += timedelta(seconds=1)
        entrada = EntradaConversa(uuid4(), self._relogio, TipoMensagem(tipo), texto, midia_url)
        self._conversas[conversa_id].entradas.append(entrada)
        return entrada

    def etapa(self, lead_id: UUID) -> Etapa:
        return self._leads[lead_id].etapa

    def definir_dono(self, lead_id: UUID, dono: str) -> None:
        self._leads[lead_id].dono = dono

    async def obter_conversa(self, conversa_id: UUID) -> ConversaLead | None:
        conversa = self._conversas.get(conversa_id)
        if conversa is None:
            return None
        lead = self._leads[conversa.lead_id]
        return ConversaLead(
            conversa_id, lead.loja_id, conversa.lead_id, lead.canal, lead.contato, lead.etapa,
            lead.dono,
        )  # fmt: skip

    async def entradas_novas(
        self, conversa_id: UUID, apos: CursorEntrada | None
    ) -> list[EntradaConversa]:
        entradas = self._conversas[conversa_id].entradas
        if apos is None:
            return list(entradas)
        return [e for e in entradas if (e.criado_em, e.id) > (apos.criado_em, apos.id)]

    async def atualizar_etapa(self, lead_id: UUID, etapa: Etapa) -> None:
        self._leads[lead_id].etapa = etapa

    async def registrar_saida(self, conversa_id: UUID, msg: MensagemSaida) -> None:
        self.saidas.append((conversa_id, msg))
