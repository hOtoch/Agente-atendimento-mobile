"""Porta de tempo: relogio monotonico injetavel e sua versao falsa para testes."""

from __future__ import annotations

from typing import Protocol


class RelogioPort(Protocol):
    def agora(self) -> float:
        """Instante monotonico, em segundos (so serve para medir intervalos)."""
        ...

    async def dormir(self, segundos: float) -> None: ...


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
