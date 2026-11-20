"""Decorator de resiliencia para `EstoquePort`: cache com TTL, retry, timeout e fallback."""

from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from typing import Any
from uuid import UUID

from app.application.estoque import CapacidadesEstoque, EstoqueIndisponivel, EstoquePort
from app.application.relogio import RelogioPort
from app.domain.estoque import ItemEstoque
from app.domain.valores import Capacidade, ModeloAparelho

_RETRYAVEIS = (EstoqueIndisponivel, TimeoutError, OSError)


@dataclass(slots=True)
class MetricasEstoque:
    """Contadores em memoria para observabilidade futura."""

    acertos_cache: int = 0
    tentativas: int = 0
    fallbacks: int = 0


@dataclass(frozen=True, slots=True)
class _Entrada:
    valor: Any
    instante: float


def _marcar(valor: Any) -> Any:
    if isinstance(valor, ItemEstoque):
        return replace(valor, desatualizado=True)
    if isinstance(valor, list):
        return [replace(i, desatualizado=True) for i in valor]
    return valor  # None (item inexistente)


class EstoqueResiliente:
    """Envolve um `EstoquePort`. `tentativas` e o total de chamadas (1 + retries)."""

    def __init__(
        self,
        adapter: EstoquePort,
        relogio: RelogioPort,
        cache_ttl_s: float = 60,
        tentativas: int = 3,
        timeout_s: float = 3.0,
        backoff_base_s: float = 0.2,
        jitter: Callable[[], float] | None = None,
    ) -> None:
        if tentativas < 1:
            raise ValueError("tentativas deve ser >= 1")
        self._adapter = adapter
        self._relogio = relogio
        self._ttl = cache_ttl_s
        self._tentativas = tentativas
        self._timeout = timeout_s
        self._backoff = backoff_base_s
        self._jitter = jitter if jitter is not None else (lambda: random.uniform(0, backoff_base_s))
        self._cache: dict[tuple[Any, ...], _Entrada] = {}
        self.metricas = MetricasEstoque()

    @property
    def capacidades(self) -> CapacidadesEstoque:
        return self._adapter.capacidades

    async def buscar(
        self,
        loja_id: UUID,
        modelo: str | ModeloAparelho,
        capacidade: Capacidade | None = None,
        cor: str | None = None,
    ) -> list[ItemEstoque]:
        alvo = modelo if isinstance(modelo, ModeloAparelho) else ModeloAparelho.de(modelo)
        cor_norm = " ".join(cor.casefold().split()) if cor is not None else None
        chave = (loja_id, "buscar", alvo, capacidade, cor_norm)
        resultado: list[ItemEstoque] = await self._executar(
            chave, lambda: self._adapter.buscar(loja_id, alvo, capacidade, cor)
        )
        return resultado

    async def obter(self, loja_id: UUID, sku: str) -> ItemEstoque | None:
        resultado: ItemEstoque | None = await self._executar(
            (loja_id, "obter", sku), lambda: self._adapter.obter(loja_id, sku)
        )
        return resultado

    async def _executar(self, chave: tuple[Any, ...], chamar: Callable[[], Awaitable[Any]]) -> Any:
        entrada = self._cache.get(chave)
        if entrada is not None and self._relogio.agora() - entrada.instante < self._ttl:
            self.metricas.acertos_cache += 1
            return entrada.valor

        for n in range(self._tentativas):
            self.metricas.tentativas += 1
            try:
                valor = await asyncio.wait_for(chamar(), self._timeout)
            except _RETRYAVEIS as exc:
                if not getattr(exc, "retentavel", True):
                    raise
                if n < self._tentativas - 1:
                    await self._relogio.dormir(self._backoff * 2**n + self._jitter())
                continue
            self._cache[chave] = _Entrada(valor, self._relogio.agora())
            return valor

        if entrada is not None:
            self.metricas.fallbacks += 1
            return _marcar(entrada.valor)
        raise EstoqueIndisponivel(f"estoque indisponivel apos {self._tentativas} tentativas")
