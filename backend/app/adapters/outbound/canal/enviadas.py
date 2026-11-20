"""Registro de ids de mensagens que a propria API enviou (para ignorar o eco `fromMe`)."""

from __future__ import annotations

from uuid import UUID

from redis.asyncio import Redis

TTL_PADRAO_S = 3600


class RegistroEnviadasMemoria:
    """Implementa `RegistroEnviadas` em memoria (testes e execucao de processo unico)."""

    def __init__(self) -> None:
        self._ids: set[tuple[UUID, str]] = set()

    async def registrar(self, loja_id: UUID, id_whatsapp: str) -> None:
        self._ids.add((loja_id, id_whatsapp))

    async def foi_enviada(self, loja_id: UUID, id_whatsapp: str) -> bool:
        return (loja_id, id_whatsapp) in self._ids


class RegistroEnviadasRedis:
    """Implementa `RegistroEnviadas` no Redis: API e worker sao processos diferentes."""

    def __init__(
        self, redis: Redis, *, prefixo: str = "whatsapp:enviada:", ttl_s: int = TTL_PADRAO_S
    ) -> None:
        self._redis = redis
        self._prefixo = prefixo
        self._ttl_s = ttl_s

    def _chave(self, loja_id: UUID, id_whatsapp: str) -> str:
        return f"{self._prefixo}{loja_id}:{id_whatsapp}"

    async def registrar(self, loja_id: UUID, id_whatsapp: str) -> None:
        await self._redis.set(self._chave(loja_id, id_whatsapp), "1", ex=self._ttl_s)

    async def foi_enviada(self, loja_id: UUID, id_whatsapp: str) -> bool:
        return bool(await self._redis.exists(self._chave(loja_id, id_whatsapp)))
