"""Barramento em memoria (so para testes: nao cruza processos)."""

import asyncio
from collections import defaultdict
from collections.abc import AsyncIterator

_FIM: dict[str, object] = {"__fim__": True}


class BarramentoEmMemoria:
    def __init__(self) -> None:
        self._filas: dict[str, list[asyncio.Queue[dict[str, object]]]] = defaultdict(list)

    async def publicar(self, topico: str, payload: dict[str, object]) -> None:
        for fila in list(self._filas[topico]):
            fila.put_nowait(payload)

    def fechar(self, topico: str) -> None:
        """Encerra os assinantes do topico (para testes de streaming)."""
        for fila in list(self._filas[topico]):
            fila.put_nowait(_FIM)

    def assinar(self, topico: str) -> AsyncIterator[dict[str, object]]:
        fila: asyncio.Queue[dict[str, object]] = asyncio.Queue()
        self._filas[topico].append(fila)  # registra ja na chamada: nada se perde
        return self._consumir(topico, fila)

    async def _consumir(
        self, topico: str, fila: asyncio.Queue[dict[str, object]]
    ) -> AsyncIterator[dict[str, object]]:
        try:
            while True:
                item = await fila.get()
                if item is _FIM:
                    return
                yield item
        finally:
            self._filas[topico].remove(fila)
