"""Limite de tentativas de login no Redis: contador por chave, com TTL = janela."""

from __future__ import annotations

from collections.abc import Sequence

from redis.asyncio import Redis

from app.application.auth.modelos import ChaveLimite


class LimiteTentativasRedis:
    def __init__(self, redis: Redis, *, janela_s: int, prefixo: str = "") -> None:
        self._r = redis
        self._janela = janela_s
        self._p = prefixo

    def _k(self, chave: ChaveLimite) -> str:
        return f"{self._p}login_falhas:{chave.chave}"

    async def bloqueado(self, chaves: Sequence[ChaveLimite]) -> int | None:
        restantes: list[int] = []
        for c in chaves:
            async with self._r.pipeline(transaction=False) as pipe:
                pipe.get(self._k(c))
                pipe.ttl(self._k(c))
                bruto, ttl = await pipe.execute()
            if bruto is not None and int(bruto) >= c.max_falhas:
                restantes.append(ttl if ttl > 0 else 1)
        return max(restantes) if restantes else None

    async def registrar_falha(self, chaves: Sequence[ChaveLimite]) -> None:
        for c in chaves:
            k = self._k(c)
            async with self._r.pipeline(transaction=True) as pipe:
                pipe.incr(k)
                pipe.ttl(k)
                _, ttl = await pipe.execute()
            if ttl < 0:  # primeira falha da janela (ou chave sem TTL): comeca a contar
                await self._r.expire(k, self._janela)

    async def limpar(self, chaves: Sequence[ChaveLimite]) -> None:
        if chaves:
            await self._r.delete(*(self._k(c) for c in chaves))
