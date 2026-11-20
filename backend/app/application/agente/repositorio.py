"""Porta de persistencia do estado do atendimento e a implementacao em memoria."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from app.application.agente.estado import EstadoAtendimento


class RepositorioAtendimento(Protocol):
    async def obter(self, loja_id: UUID, lead_id: UUID) -> EstadoAtendimento:
        """Ultima versao do estado; estado vazio se o lead ainda nao tem registro."""
        ...

    async def salvar(self, loja_id: UUID, lead_id: UUID, estado: EstadoAtendimento) -> int:
        """Grava uma NOVA versao (historico preservado) e devolve o numero dela."""
        ...


class RepositorioAtendimentoEmMemoria:
    def __init__(self) -> None:
        self._versoes: dict[tuple[UUID, UUID], list[EstadoAtendimento]] = {}

    async def obter(self, loja_id: UUID, lead_id: UUID) -> EstadoAtendimento:
        versoes = self._versoes.get((loja_id, lead_id))
        return versoes[-1] if versoes else EstadoAtendimento()

    async def salvar(self, loja_id: UUID, lead_id: UUID, estado: EstadoAtendimento) -> int:
        versoes = self._versoes.setdefault((loja_id, lead_id), [])
        versoes.append(estado)
        return len(versoes)
