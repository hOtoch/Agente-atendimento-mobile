"""Buffer por conversa (debounce), trava e processamento "quando quieto".

O cliente manda varias mensagens seguidas; so processamos quando passou `janela_s` desde a
ULTIMA, e nunca dois workers na mesma conversa ao mesmo tempo. Este modulo so define portas
(`Protocol`), o caso de uso e implementacoes em memoria para testes; Redis/arq ficam em infra.

Contrato do agendador (o timestamp da ultima mensagem fica guardado nele, pois API e worker sao
processos diferentes):

- `agendar`: registra uma mensagem nova e agenda o job para agora + janela.
- `pendente`: instante da ultima mensagem ainda nao processada (ou None).
- `reagendar`: agenda o job de novo daqui a `atraso_s`. Sem `nova_tentativa`, e idempotente para a
  mesma ultima mensagem (nao duplica o job ja agendado por `agendar`); com `nova_tentativa=True`
  cria um job novo (usado quando a trava estava ocupada).
- `concluir`: marca como processado ate `ate`, a menos que tenha chegado mensagem mais nova.
"""

from __future__ import annotations

import heapq
from collections.abc import Awaitable, Callable
from typing import Protocol
from uuid import UUID

from app.application.relogio import RelogioPort


class AgendadorConversas(Protocol):
    async def agendar(self, conversa_id: UUID) -> None: ...

    async def pendente(self, conversa_id: UUID) -> float | None: ...

    async def reagendar(
        self, conversa_id: UUID, atraso_s: float, *, nova_tentativa: bool = False
    ) -> None: ...

    async def concluir(self, conversa_id: UUID, ate: float) -> None: ...


class TravaConversa(Protocol):
    async def adquirir(self, conversa_id: UUID, ttl_s: float) -> bool: ...

    async def liberar(self, conversa_id: UUID) -> None: ...


class ProcessarQuandoQuieto:
    """Corpo do job: so processa se a janela passou desde a ultima mensagem e se ha trava."""

    def __init__(
        self,
        *,
        agendador: AgendadorConversas,
        trava: TravaConversa,
        relogio: RelogioPort,
        processar: Callable[[UUID], Awaitable[None]],
        janela_s: float = 10.0,
        trava_ttl_s: float = 120.0,
        espera_trava_s: float = 1.0,
    ) -> None:
        self._agendador = agendador
        self._trava = trava
        self._relogio = relogio
        self._processar = processar
        self._janela_s = janela_s
        self._trava_ttl_s = trava_ttl_s
        self._espera_trava_s = espera_trava_s

    async def __call__(self, conversa_id: UUID) -> None:
        ultima = await self._agendador.pendente(conversa_id)
        if ultima is None:
            # nada novo desde o ultimo processamento (job duplicado ou atrasado)
            return
        decorrido = self._relogio.agora() - ultima
        if decorrido < self._janela_s:
            await self._agendador.reagendar(conversa_id, self._janela_s - decorrido)
            return
        if not await self._trava.adquirir(conversa_id, self._trava_ttl_s):
            await self._agendador.reagendar(conversa_id, self._espera_trava_s, nova_tentativa=True)
            return
        try:
            await self._processar(conversa_id)
        finally:
            await self._trava.liberar(conversa_id)
        await self._agendador.concluir(conversa_id, ultima)


class TravaEmMemoria:
    """Trava com ttl sobre o relogio injetado (para testes)."""

    def __init__(self, relogio: RelogioPort) -> None:
        self._relogio = relogio
        self._expira_em: dict[UUID, float] = {}

    async def adquirir(self, conversa_id: UUID, ttl_s: float) -> bool:
        agora = self._relogio.agora()
        if self._expira_em.get(conversa_id, float("-inf")) > agora:
            return False
        self._expira_em[conversa_id] = agora + ttl_s
        return True

    async def liberar(self, conversa_id: UUID) -> None:
        self._expira_em.pop(conversa_id, None)


class AgendadorEmMemoria:
    """Agendador de testes: guarda os jobs numa fila e os roda avancando o relogio falso.

    Imita o arq: o job so some depois de executar e um `job_id` repetido e ignorado.
    """

    def __init__(self, relogio: RelogioPort, *, janela_s: float = 10.0) -> None:
        self._relogio = relogio
        self._janela_s = janela_s
        self._ultima: dict[UUID, float] = {}
        self._fila: list[tuple[float, int, str, UUID]] = []
        self._ids: set[str] = set()
        self._seq = 0

    def _enfileirar(self, job_id: str, conversa_id: UUID, quando: float) -> None:
        if job_id in self._ids:
            return
        self._ids.add(job_id)
        self._seq += 1
        heapq.heappush(self._fila, (quando, self._seq, job_id, conversa_id))

    async def agendar(self, conversa_id: UUID) -> None:
        agora = self._relogio.agora()
        self._ultima[conversa_id] = agora
        self._enfileirar(f"{conversa_id}:{agora}", conversa_id, agora + self._janela_s)

    async def pendente(self, conversa_id: UUID) -> float | None:
        return self._ultima.get(conversa_id)

    async def reagendar(
        self, conversa_id: UUID, atraso_s: float, *, nova_tentativa: bool = False
    ) -> None:
        agora = self._relogio.agora()
        job_id = f"{conversa_id}:{self._ultima[conversa_id]}"
        if nova_tentativa:
            job_id += f":t{agora}"
        self._enfileirar(job_id, conversa_id, agora + atraso_s)

    async def concluir(self, conversa_id: UUID, ate: float) -> None:
        if self._ultima.get(conversa_id) == ate:
            del self._ultima[conversa_id]

    async def rodar_ate_ocioso(self, executar: Callable[[UUID], Awaitable[None]]) -> None:
        """Roda os jobs em ordem de horario ate a fila esvaziar, avancando o relogio falso."""
        while self._fila:
            quando, _, job_id, conversa_id = heapq.heappop(self._fila)
            espera = quando - self._relogio.agora()
            if espera > 0:
                await self._relogio.dormir(espera)
            try:
                await executar(conversa_id)
            finally:
                self._ids.discard(job_id)
