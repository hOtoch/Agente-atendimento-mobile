"""Implementacoes em memoria das portas do follow-up (testes unitarios; sem IO)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.application.agente.conversa_portas import DONO_IA
from app.application.canal import Canal, MensagemSaida
from app.application.followup import CandidatoFollowup
from app.domain.followup import ConfigFollowup
from app.domain.kanban import Etapa


class ConfigFollowupEmMemoria:
    def __init__(self) -> None:
        self._configs: dict[UUID, ConfigFollowup] = {}

    async def obter(self, loja_id: UUID) -> ConfigFollowup:
        return self._configs.get(loja_id, ConfigFollowup.padrao())

    async def salvar(self, loja_id: UUID, config: ConfigFollowup) -> None:
        self._configs[loja_id] = config

    async def lojas_com_followup_ligado(self) -> list[UUID]:
        return [loja for loja, c in self._configs.items() if c.ligado]


@dataclass(slots=True)
class _Lead:
    loja_id: UUID
    conversa_id: UUID
    canal: Canal
    contato: str
    etapa: Etapa
    dono: str


@dataclass(frozen=True, slots=True)
class _Mensagem:
    autor: str
    em: datetime


class FollowupEmMemoria:
    """Leads, mensagens e tentativas. Implementa `RepositorioFollowup`, `RegistroTentativas` e
    `RegistroSaida`; a saida da IA e carimbada com o relogio injetado."""

    def __init__(self, relogio: Callable[[], datetime]) -> None:
        self._relogio = relogio
        self._leads: dict[UUID, _Lead] = {}
        self._mensagens: dict[UUID, list[_Mensagem]] = {}  # por lead
        self._followups: dict[UUID, list[datetime]] = {}
        self.saidas: list[tuple[UUID, MensagemSaida]] = []

    def adicionar_lead(
        self,
        *,
        loja_id: UUID,
        lead_id: UUID,
        conversa_id: UUID,
        etapa: Etapa,
        dono: str = DONO_IA,
        canal: Canal = Canal.WEBCHAT,
        contato: str = "contato-1",
    ) -> None:
        self._leads[lead_id] = _Lead(loja_id, conversa_id, canal, contato, etapa, dono)
        self._mensagens[lead_id] = []
        self._followups[lead_id] = []

    def mensagem(self, lead_id: UUID, autor: str, em: datetime) -> None:
        """`autor`: cliente | ia | vendedor."""
        self._mensagens[lead_id].append(_Mensagem(autor, em))

    def definir_dono(self, lead_id: UUID, dono: str) -> None:
        self._leads[lead_id].dono = dono

    def followups_enviados(self, lead_id: UUID) -> list[datetime]:
        return list(self._followups[lead_id])

    async def listar_candidatos(
        self, loja_id: UUID, etapas: list[Etapa], parado_antes_de: datetime
    ) -> list[CandidatoFollowup]:
        candidatos = []
        for lead_id, lead in self._leads.items():
            mensagens = sorted(self._mensagens[lead_id], key=lambda m: m.em)
            if lead.loja_id != loja_id or lead.etapa not in etapas or not mensagens:
                continue
            ultima = mensagens[-1]
            if ultima.em >= parado_antes_de:
                continue
            do_cliente = [m.em for m in mensagens if m.autor == "cliente"]
            ultima_cliente = do_cliente[-1] if do_cliente else None
            envios = self._followups[lead_id]
            tentativas = [e for e in envios if ultima_cliente is None or e > ultima_cliente]
            candidatos.append(
                CandidatoFollowup(
                    loja_id=loja_id,
                    lead_id=lead_id,
                    conversa_id=lead.conversa_id,
                    canal=lead.canal,
                    contato=lead.contato,
                    etapa=lead.etapa,
                    dono=lead.dono,
                    ultima_mensagem_em=ultima.em,
                    ultima_mensagem_do_cliente=ultima.autor == "cliente",
                    tentativas=len(tentativas),
                    ultimo_followup_em=max(envios) if envios else None,
                )
            )
        return candidatos

    async def registrar(
        self, loja_id: UUID, lead_id: UUID, *, tentativa: int, etapa: Etapa, em: datetime
    ) -> None:
        self._followups[lead_id].append(em)

    async def registrar_saida(self, conversa_id: UUID, msg: MensagemSaida) -> None:
        self.saidas.append((conversa_id, msg))
        for lead_id, lead in self._leads.items():
            if lead.conversa_id == conversa_id:
                self.mensagem(lead_id, "ia", self._relogio())
