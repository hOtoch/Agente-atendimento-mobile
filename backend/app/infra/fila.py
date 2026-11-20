"""Fila de debounce por conversa (arq + Redis) e trava distribuida.

Decisao sobre `_job_id` / `_defer_by` (conferida em arq 0.28, `ArqRedis.enqueue_job`):

- O arq NAO substitui um job adiado: se ja existe a chave do job (ou o resultado), `enqueue_job`
  devolve `None` e ignora o duplicado. Alem disso a chave so e apagada quando o job TERMINA, entao
  um `_job_id` fixo por conversa perderia a mensagem que chega enquanto o job roda.
- Por isso o `_job_id` e deterministico por (conversa, ultima mensagem):
  `conversa:{id}:{ts_ms}`. Cada mensagem nova cria seu job com `_defer_by=janela`; reenfileirar a
  MESMA mensagem e ignorado (idempotencia). Quando um job antigo dispara e ve que chegou mensagem
  mais nova, `reagendar` cai no id do job mais novo, que ja existe, e nada se duplica: so o job da
  ultima mensagem processa. O estado "ultima mensagem nao processada" fica em
  `ultima_mensagem:{id}` (Redis), compartilhado entre API e workers.
- Quando a trava esta ocupada, `reagendar(nova_tentativa=True)` usa um id novo (o job atual ainda
  ocupa a chave do seu id enquanto roda).
"""

from __future__ import annotations

import asyncio
import time
import uuid
from uuid import UUID

from arq.connections import ArqRedis

FUNCAO_PROCESSAR = "processar_conversa"
_EXPIRA_ULTIMA_S = 24 * 3600

_LUA_LIBERAR = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
end
return 0
"""


class RelogioParede:
    """Relogio de parede (epoch): comparavel entre processos, ao contrario do monotonico."""

    def agora(self) -> float:
        return time.time()

    async def dormir(self, segundos: float) -> None:
        await asyncio.sleep(segundos)


def _ms(segundos: float) -> int:
    return round(segundos * 1000)


class AgendadorArq:
    def __init__(
        self,
        redis: ArqRedis,
        *,
        janela_s: float = 4.0,
        prefixo: str = "",
        nome_fila: str | None = None,
    ) -> None:
        self._redis = redis
        self._janela_s = janela_s
        self._prefixo = prefixo
        self._nome_fila = nome_fila

    def _chave(self, conversa_id: UUID) -> str:
        return f"{self._prefixo}ultima_mensagem:{conversa_id}"

    async def _enfileirar(self, conversa_id: UUID, job_id: str, atraso_s: float) -> None:
        await self._redis.enqueue_job(
            FUNCAO_PROCESSAR,
            str(conversa_id),
            _job_id=f"{self._prefixo}{job_id}",
            _defer_by=max(atraso_s, 0.0),
            _queue_name=self._nome_fila,
        )

    async def agendar(self, conversa_id: UUID) -> None:
        ts_ms = _ms(time.time())
        await self._redis.set(self._chave(conversa_id), str(ts_ms), ex=_EXPIRA_ULTIMA_S)
        await self._enfileirar(conversa_id, f"conversa:{conversa_id}:{ts_ms}", self._janela_s)

    async def pendente(self, conversa_id: UUID) -> float | None:
        bruto = await self._redis.get(self._chave(conversa_id))
        return None if bruto is None else int(bruto) / 1000

    async def reagendar(
        self, conversa_id: UUID, atraso_s: float, *, nova_tentativa: bool = False
    ) -> None:
        ultima = await self.pendente(conversa_id)
        if ultima is None:
            return
        job_id = f"conversa:{conversa_id}:{_ms(ultima)}"
        if nova_tentativa:
            job_id += f":t{uuid.uuid4().hex[:8]}"
        await self._enfileirar(conversa_id, job_id, atraso_s)

    async def concluir(self, conversa_id: UUID, ate: float) -> None:
        await self._redis.eval(_LUA_LIBERAR, 1, self._chave(conversa_id), str(_ms(ate)))  # type: ignore[misc]


class TravaRedis:
    """`SET NX PX` com token por posse; libera com compare-and-delete atomico (Lua)."""

    def __init__(self, redis: ArqRedis, *, prefixo: str = "") -> None:
        self._redis = redis
        self._prefixo = prefixo
        self._tokens: dict[UUID, str] = {}

    def _chave(self, conversa_id: UUID) -> str:
        return f"{self._prefixo}trava:{conversa_id}"

    async def adquirir(self, conversa_id: UUID, ttl_s: float) -> bool:
        token = uuid.uuid4().hex
        ok = await self._redis.set(self._chave(conversa_id), token, nx=True, px=_ms(ttl_s))
        if ok:
            self._tokens[conversa_id] = token
        return bool(ok)

    async def liberar(self, conversa_id: UUID) -> None:
        token = self._tokens.pop(conversa_id, None)
        if token is None:
            return
        await self._redis.eval(_LUA_LIBERAR, 1, self._chave(conversa_id), token)  # type: ignore[misc]
