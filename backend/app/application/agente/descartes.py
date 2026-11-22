"""Contagem de respostas descartadas em seguida, por conversa.

Quando o cliente escreve enquanto a IA gera a resposta, a resposta e descartada e a proxima
rodada responde a tudo junto (ver `processar_conversa`). Para quem escreve sem parar nao ficar
sem resposta, so ha `max_descartes` descartes seguidos; o contador vive fora do caso de uso
porque cada rodada (job) monta um `ProcessarConversa` novo, possivelmente em outro worker.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Protocol
from uuid import UUID


class ContadorDescartes(Protocol):
    async def registrar(self, conversa_id: UUID) -> int:
        """Soma um descarte e devolve o total seguido."""
        ...

    async def atual(self, conversa_id: UUID) -> int: ...

    async def zerar(self, conversa_id: UUID) -> None:
        """Chamado quando uma resposta e de fato enviada."""
        ...


class DescartesEmMemoria:
    def __init__(self) -> None:
        self._total: defaultdict[UUID, int] = defaultdict(int)

    async def registrar(self, conversa_id: UUID) -> int:
        self._total[conversa_id] += 1
        return self._total[conversa_id]

    async def atual(self, conversa_id: UUID) -> int:
        return self._total.get(conversa_id, 0)

    async def zerar(self, conversa_id: UUID) -> None:
        self._total.pop(conversa_id, None)
