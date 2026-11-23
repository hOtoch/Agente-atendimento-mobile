"""Sessoes no Redis: so o hash SHA-256 do token vai para o servidor, nunca o token."""

from __future__ import annotations

import hashlib
import json
import secrets
from collections.abc import Awaitable
from typing import Any, cast
from uuid import UUID

from redis.asyncio import Redis

from app.application.auth.modelos import DadosSessao


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class SessoesRedis:
    def __init__(self, redis: Redis, *, ttl_s: int, prefixo: str = "") -> None:
        self._r = redis
        self._ttl = ttl_s
        self._p = prefixo

    def _chave(self, h: str) -> str:
        return f"{self._p}sessao:{h}"

    def _chave_usuario(self, usuario_id: UUID) -> str:
        return f"{self._p}sessoes_usuario:{usuario_id}"

    async def criar(self, usuario_id: UUID, loja_id: UUID) -> str:
        token = secrets.token_urlsafe(32)
        h = _hash(token)
        valor = json.dumps({"usuario_id": str(usuario_id), "loja_id": str(loja_id)})
        indice = self._chave_usuario(usuario_id)
        async with self._r.pipeline(transaction=True) as pipe:
            pipe.set(self._chave(h), valor, ex=self._ttl)
            pipe.sadd(indice, h)
            pipe.expire(indice, self._ttl)
            await pipe.execute()
        return token

    async def obter(self, token: str) -> DadosSessao | None:
        bruto = await self._r.get(self._chave(_hash(token)))
        if bruto is None:
            return None
        dados = json.loads(bruto)
        return DadosSessao(UUID(dados["usuario_id"]), UUID(dados["loja_id"]))

    async def renovar(self, token: str) -> bool:
        h = _hash(token)
        dados = await self.obter(token)
        if dados is None:
            return False
        async with self._r.pipeline(transaction=True) as pipe:
            pipe.expire(self._chave(h), self._ttl)
            pipe.expire(self._chave_usuario(dados.usuario_id), self._ttl)
            resultados = await pipe.execute()
        return bool(resultados[0])

    async def encerrar(self, token: str) -> None:
        h = _hash(token)
        dados = await self.obter(token)
        async with self._r.pipeline(transaction=True) as pipe:
            pipe.delete(self._chave(h))
            if dados is not None:
                pipe.srem(self._chave_usuario(dados.usuario_id), h)
            await pipe.execute()

    async def encerrar_do_usuario(self, usuario_id: UUID, *, manter: str | None = None) -> None:
        indice = self._chave_usuario(usuario_id)
        manter_h = _hash(manter) if manter is not None else None
        membros = {
            m.decode() if isinstance(m, bytes) else str(m)
            for m in await cast(Awaitable[set[Any]], self._r.smembers(indice))
        }
        for h in membros - {manter_h}:
            async with self._r.pipeline(transaction=True) as pipe:
                pipe.delete(self._chave(h))
                pipe.srem(indice, h)
                await pipe.execute()
