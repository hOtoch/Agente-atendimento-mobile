"""Barramento sobre Redis pub/sub: cruza processos (API <-> worker)."""

import json
from collections.abc import AsyncIterator

from redis.asyncio import Redis


class BarramentoRedis:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def publicar(self, topico: str, payload: dict[str, object]) -> None:
        await self._redis.publish(topico, json.dumps(payload))

    async def assinar(self, topico: str) -> AsyncIterator[dict[str, object]]:
        pubsub = self._redis.pubsub()
        await pubsub.subscribe(topico)
        try:
            async for item in pubsub.listen():
                if item["type"] != "message":
                    continue
                dados: dict[str, object] = json.loads(item["data"])
                yield dados
        finally:
            await pubsub.unsubscribe(topico)
            await pubsub.aclose()  # type: ignore[no-untyped-call]
