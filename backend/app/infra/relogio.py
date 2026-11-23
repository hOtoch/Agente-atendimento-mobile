"""Relogio real (implementa `RelogioPort`)."""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime


class RelogioSistema:
    def agora(self) -> float:
        return time.monotonic()

    async def dormir(self, segundos: float) -> None:
        await asyncio.sleep(segundos)


class RelogioParedeSistema:
    """Hora real em UTC (implementa `RelogioParedePort`)."""

    def agora(self) -> datetime:
        return datetime.now(UTC)
