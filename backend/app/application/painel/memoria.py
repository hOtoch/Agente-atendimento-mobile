"""Implementacoes em memoria das portas do painel (testes unitarios; sem IO)."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from app.application.agente.estado import EstadoAtendimento
from app.application.canal import Canal, TipoMensagem
from app.application.painel.eventos import EventoPainel
from app.application.painel.portas import (
    AUTOR_VENDEDOR,
    DONO_IA,
    EventoRegistro,
    LeadRegistro,
    MensagemRegistro,
)
from app.domain.kanban import Etapa

_INICIO = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)


class PublicadorEmMemoria:
    """Guarda `(loja_id, evento)`; `falhar = True` simula o barramento fora do ar."""

    def __init__(self) -> None:
        self.publicados: list[tuple[UUID, EventoPainel]] = []
        self.falhar = False

    async def publicar(self, loja_id: UUID, evento: EventoPainel) -> None:
        if self.falhar:
            raise ConnectionError("barramento fora do ar")
        self.publicados.append((loja_id, evento))


class RepositorioPainelEmMemoria:
    def __init__(self) -> None:
        self.leads: dict[UUID, LeadRegistro] = {}
        self._vendedores: dict[UUID, tuple[UUID, str]] = {}
        self._mensagens: dict[UUID, list[MensagemRegistro]] = {}
        self._eventos: dict[UUID, list[EventoRegistro]] = {}
        self._relogio = _INICIO

    def _tick(self) -> datetime:
        self._relogio += timedelta(seconds=1)
        return self._relogio

    # --- montagem do cenario ----------------------------------------------------------------

    def adicionar_vendedor(self, loja_id: UUID, vendedor_id: UUID, nome: str) -> None:
        self._vendedores[vendedor_id] = (loja_id, nome)

    def adicionar_lead(
        self,
        loja_id: UUID,
        *,
        telefone: str,
        nome: str | None = None,
        canal: Canal = Canal.WEBCHAT,
        etapa: Etapa = Etapa.NOVO_CONTATO,
        etapa_desde: datetime | None = None,
        dono: str = DONO_IA,
        vendedor_id: UUID | None = None,
        estado: EstadoAtendimento | None = None,
    ) -> UUID:
        lead_id = uuid4()
        agora = self._tick()
        self.leads[lead_id] = LeadRegistro(
            id=lead_id,
            loja_id=loja_id,
            conversa_id=uuid4(),
            nome=nome,
            telefone=telefone,
            canal=canal,
            etapa=etapa,
            etapa_desde=etapa_desde or agora,
            dono=dono,
            vendedor_id=vendedor_id,
            vendedor_nome=self._nome_vendedor(vendedor_id),
            criado_em=agora,
            estado=estado or EstadoAtendimento(),
        )
        return lead_id

    def adicionar_mensagem(self, lead_id: UUID, *, autor: str, texto: str) -> None:
        lead = self.leads[lead_id]
        assert lead.conversa_id is not None
        direcao = "entrada" if autor == "cliente" else "saida"
        self._mensagens.setdefault(lead_id, []).append(
            MensagemRegistro(
                uuid4(),
                lead.conversa_id,
                direcao,
                autor,
                TipoMensagem.TEXTO,
                texto,
                None,
                self._tick(),
            )  # fmt: skip
        )

    def adicionar_evento(self, lead_id: UUID, tipo: str, payload: dict[str, Any]) -> None:
        self._eventos.setdefault(lead_id, []).append(
            EventoRegistro(uuid4(), tipo, payload, self._tick())
        )

    def eventos_de(self, lead_id: UUID) -> list[EventoRegistro]:
        return list(self._eventos.get(lead_id, []))

    def _nome_vendedor(self, vendedor_id: UUID | None) -> str | None:
        if vendedor_id is None or vendedor_id not in self._vendedores:
            return None
        return self._vendedores[vendedor_id][1]

    # --- porta ------------------------------------------------------------------------------

    async def listar_leads(self, loja_id: UUID) -> list[LeadRegistro]:
        return [x for x in self.leads.values() if x.loja_id == loja_id]

    async def obter_lead(self, loja_id: UUID, lead_id: UUID) -> LeadRegistro | None:
        lead = self.leads.get(lead_id)
        return lead if lead is not None and lead.loja_id == loja_id else None

    async def listar_mensagens(self, loja_id: UUID, lead_id: UUID) -> list[MensagemRegistro]:
        return list(self._mensagens.get(lead_id, []))

    async def listar_eventos(self, loja_id: UUID, lead_id: UUID) -> list[EventoRegistro]:
        return self.eventos_de(lead_id)

    async def vendedor_existe(self, loja_id: UUID, vendedor_id: UUID) -> bool:
        achado = self._vendedores.get(vendedor_id)
        return achado is not None and achado[0] == loja_id

    async def mover_etapa(
        self, loja_id: UUID, lead_id: UUID, etapa: Etapa, payload_evento: dict[str, Any]
    ) -> None:
        agora = self._tick()
        self.leads[lead_id] = replace(self.leads[lead_id], etapa=etapa, etapa_desde=agora)
        self.adicionar_evento(lead_id, "etapa_mudou", payload_evento)

    async def definir_dono(
        self,
        loja_id: UUID,
        lead_id: UUID,
        dono: str,
        vendedor_id: UUID | None,
        payload_evento: dict[str, Any],
    ) -> None:
        lead = self.leads[lead_id]
        novo = vendedor_id if vendedor_id is not None else lead.vendedor_id
        self.leads[lead_id] = replace(
            lead, dono=dono, vendedor_id=novo, vendedor_nome=self._nome_vendedor(novo)
        )
        self.adicionar_evento(lead_id, "dono_mudou", payload_evento)

    async def registrar_mensagem_vendedor(
        self, loja_id: UUID, conversa_id: UUID, canal: Canal, texto: str
    ) -> MensagemRegistro:
        lead_id = next(i for i, x in self.leads.items() if x.conversa_id == conversa_id)
        msg = MensagemRegistro(
            uuid4(), conversa_id, "saida", AUTOR_VENDEDOR, TipoMensagem.TEXTO, texto, None,
            self._tick(),
        )  # fmt: skip
        self._mensagens.setdefault(lead_id, []).append(msg)
        return msg
