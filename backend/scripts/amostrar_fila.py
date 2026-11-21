"""Amostra a fila arq (Redis) e as mensagens do banco a cada segundo, em CSV.

    cd backend
    uv run python scripts/amostrar_fila.py --redis-url redis://localhost:6379/5 \\
        --database-url postgresql+asyncpg://... --saida ../infra/k6/saida/fila.csv

Colunas: `t` (epoch), `zcard` (jobs na fila, inclusive os adiados pelo debounce), `prontos`
(vencidos, esperando worker livre), `em_execucao`, `entradas` e `saidas` (mensagens da IA).
Roda ate receber SIGINT/SIGTERM.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import signal
import sys
import time
from collections.abc import Sequence
from pathlib import Path

CABECALHO = "t,zcard,prontos,em_execucao,entradas,saidas\n"
FILA = "arq:queue"
PREFIXO_EXECUCAO = "arq:in-progress:*"


async def _amostrar(redis_url: str, database_url: str, saida: Path, intervalo_s: float) -> None:
    from redis.asyncio import Redis
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    redis = Redis.from_url(redis_url)
    engine = create_async_engine(database_url)
    parar = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sinal in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sinal, parar.set)
    consulta = text(
        "SELECT count(*) FILTER (WHERE direcao = 'entrada'), "
        "count(*) FILTER (WHERE autor = 'ia') FROM mensagens"
    )
    try:
        with saida.open("w", encoding="utf-8", buffering=1) as f:
            f.write(CABECALHO)
            async with engine.connect() as conn:
                while not parar.is_set():
                    agora = time.time()
                    zcard = await redis.zcard(FILA)
                    prontos = await redis.zcount(FILA, "-inf", int(agora * 1000))
                    em_execucao = 0
                    async for _ in redis.scan_iter(match=PREFIXO_EXECUCAO, count=500):
                        em_execucao += 1
                    entradas, saidas = (await conn.execute(consulta)).one()
                    await conn.rollback()  # nova transacao a cada leitura
                    f.write(f"{agora:.3f},{zcard},{prontos},{em_execucao},{entradas},{saidas}\n")
                    with contextlib.suppress(TimeoutError):
                        await asyncio.wait_for(parar.wait(), intervalo_s)
    finally:
        await redis.aclose()
        await engine.dispose()


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--redis-url", required=True)
    ap.add_argument("--database-url", required=True)
    ap.add_argument("--saida", type=Path, required=True)
    ap.add_argument("--intervalo", type=float, default=1.0)
    a = ap.parse_args(argv)
    asyncio.run(_amostrar(a.redis_url, a.database_url, a.saida, a.intervalo))
    return 0


if __name__ == "__main__":
    sys.exit(main())
