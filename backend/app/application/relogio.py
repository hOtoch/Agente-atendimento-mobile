"""Porta de tempo: relogio monotonico injetavel e sua versao falsa para testes."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Protocol


class RelogioPort(Protocol):
    def agora(self) -> float:
        """Instante monotonico, em segundos (so serve para medir intervalos)."""
        ...

    async def dormir(self, segundos: float) -> None: ...


class RelogioParedePort(Protocol):
    """Relogio de parede (UTC): serve para comparar com horarios gravados, nao para medir."""

    def agora(self) -> datetime:
        """Instante atual com fuso (UTC)."""
        ...


class RelogioFalso:
    """Relogio de testes: `dormir` avanca o tempo sem esperar e registra a pausa."""

    def __init__(self, inicio: float = 0.0) -> None:
        self._agora = inicio
        self.dormidos: list[float] = []

    def agora(self) -> float:
        return self._agora

    async def dormir(self, segundos: float) -> None:
        self.dormidos.append(segundos)
        self._agora += segundos

    def avancar(self, segundos: float) -> None:
        self._agora += segundos


class RelogioParedeFalso:
    """Relogio de parede de testes: o tempo so anda por `avancar`/`definir`."""

    def __init__(self, inicio: datetime | None = None) -> None:
        self._agora = inicio or datetime(2026, 11, 20, 12, 0, tzinfo=UTC)

    def agora(self) -> datetime:
        return self._agora

    def avancar(self, segundos: float) -> None:
        self._agora += timedelta(seconds=segundos)

    def definir(self, instante: datetime) -> None:
        self._agora = instante
