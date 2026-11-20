"""Relogio real (implementa `RelogioPort`)."""

from __future__ import annotations

import asyncio
import time


class RelogioSistema:
    def agora(self) -> float:
        return time.monotonic()

    async def dormir(self, segundos: float) -> None:
        await asyncio.sleep(segundos)
