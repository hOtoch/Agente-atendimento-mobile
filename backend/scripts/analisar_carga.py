"""Resume um teste de carga: ingestao (k6), fila, throughput do worker e latencia ate a resposta.

    cd backend
    uv run python scripts/analisar_carga.py --k6-json ../infra/k6/saida/eventos.json \\
        --k6-resumo ../infra/k6/saida/resumo.json --stub-log ../infra/k6/saida/stub.jsonl \\
        --fila-csv ../infra/k6/saida/fila.csv --fim-carga <epoch>

Entradas: NDJSON do k6 (`--out json`), `--summary-export` do k6, log da Evolution falsa
(`infra/k6/stub_evolution.py`) e o CSV de `scripts/amostrar_fila.py`.
"""

from __future__ import annotations

import argparse
import bisect
import csv
import json
import math
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

METRICA = "msg_enviada"
ROTA_TEXTO = "/message/sendText/"


@dataclass(frozen=True, slots=True)
class Amostra:
    t: float
    zcard: int
    prontos: int
    em_execucao: int
    entradas: int
    saidas: int


@dataclass(frozen=True, slots=True)
class ResumoFila:
    max_zcard: int
    max_prontos: int
    max_em_execucao: int
    esvaziou_em_s: float | None
    """Segundos entre o fim da carga e a primeira amostra com fila e workers zerados."""


@dataclass(frozen=True, slots=True)
class Throughput:
    total: int
    media_por_min: float
    pico_por_min: int
    """Maior numero de envios em qualquer janela de 60 s."""


def percentis(
    valores: Sequence[float], ps: Sequence[int] = (50, 95, 99)
) -> dict[int, float | None]:
    """Percentis pelo metodo do posto mais proximo; `None` se nao ha dados."""
    if not valores:
        return {p: None for p in ps}
    ordenados = sorted(valores)
    n = len(ordenados)
    return {p: ordenados[max(math.ceil(p / 100 * n), 1) - 1] for p in ps}


def resumir_fila(amostras: Sequence[Amostra], fim_carga: float) -> ResumoFila:
    esvaziou = next(
        (
            a.t - fim_carga
            for a in amostras
            if a.t >= fim_carga and a.zcard == 0 and a.em_execucao == 0
        ),
        None,
    )
    return ResumoFila(
        max_zcard=max((a.zcard for a in amostras), default=0),
        max_prontos=max((a.prontos for a in amostras), default=0),
        max_em_execucao=max((a.em_execucao for a in amostras), default=0),
        esvaziou_em_s=esvaziou,
    )


def throughput(envios: Sequence[float], janela_s: float = 60.0) -> Throughput:
    ordenados = sorted(envios)
    if not ordenados:
        return Throughput(0, 0.0, 0)
    pico = 0
    for i, inicio in enumerate(ordenados):
        pico = max(pico, bisect.bisect_left(ordenados, inicio + janela_s) - i)
    duracao = ordenados[-1] - ordenados[0]
    media = len(ordenados) / duracao * 60 if duracao > 0 else float(len(ordenados))
    return Throughput(len(ordenados), media, pico)


def latencias_resposta(
    mensagens: Sequence[tuple[float, str]], respostas: Sequence[tuple[float, str]]
) -> list[float]:
    """Para cada resposta: segundos desde a ULTIMA mensagem do cliente (mesmo numero) anterior."""
    por_numero: dict[str, list[float]] = {}
    for t, numero in sorted(mensagens):
        por_numero.setdefault(numero, []).append(t)
    saida: list[float] = []
    for t, numero in respostas:
        tempos = por_numero.get(numero, [])
        i = bisect.bisect_right(tempos, t)
        if i:
            saida.append(round(t - tempos[i - 1], 6))
    return saida


def ler_amostras(arquivo: Path) -> list[Amostra]:
    with arquivo.open(newline="", encoding="utf-8") as f:
        return [
            Amostra(
                t=float(r["t"]),
                zcard=int(r["zcard"]),
                prontos=int(r["prontos"]),
                em_execucao=int(r["em_execucao"]),
                entradas=int(r["entradas"]),
                saidas=int(r["saidas"]),
            )
            for r in csv.DictReader(f)
        ]


def ler_envios_stub(arquivo: Path) -> list[tuple[float, str]]:
    """`(epoch, numero)` de cada texto enviado ao cliente (a Evolution falsa os registra)."""
    envios: list[tuple[float, str]] = []
    for linha in arquivo.read_text(encoding="utf-8").splitlines():
        try:
            evento = json.loads(linha)
        except ValueError:
            continue
        if str(evento.get("rota", "")).startswith(ROTA_TEXTO):
            envios.append((float(evento["t"]), str(evento.get("numero"))))
    return envios


def ler_mensagens_k6(linhas: Iterable[str]) -> list[tuple[float, str]]:
    """`(epoch, numero)` de cada mensagem unica do cliente (ignora as reentregas)."""
    vistos: set[str] = set()
    saida: list[tuple[float, str]] = []
    for linha in linhas:
        try:
            evento = json.loads(linha)
        except ValueError:
            continue
        if evento.get("type") != "Point" or evento.get("metric") != METRICA:
            continue
        dados = evento.get("data", {})
        tags = dados.get("tags", {})
        id_wa = str(tags.get("id_wa", ""))
        if tags.get("reentrega") == "1" or id_wa in vistos:
            continue
        vistos.add(id_wa)
        saida.append((datetime.fromisoformat(dados["time"]).timestamp(), str(tags.get("numero"))))
    return saida


def _fmt(valor: float | None, casas: int = 1) -> str:
    return "n/d" if valor is None else f"{valor:.{casas}f}"


def formatar(
    resumo_k6: dict[str, object] | None,
    fila: ResumoFila,
    tput: Throughput,
    latencias: Sequence[float],
) -> str:
    linhas: list[str] = []
    if resumo_k6:
        metricas = resumo_k6.get("metrics", {})
        assert isinstance(metricas, dict)
        dur = metricas.get("http_req_duration", {})
        reqs = metricas.get("http_reqs", {})
        linhas += [
            "== Ingestao (k6, latencia do webhook em ms) ==",
            f"requisicoes: {reqs.get('count', 'n/d')}  ({_fmt(reqs.get('rate'))}/s)",
            "p50={} p90={} p95={} p99={} max={}".format(
                _fmt(dur.get("med")),
                _fmt(dur.get("p(90)")),
                _fmt(dur.get("p(95)")),
                _fmt(dur.get("p(99)")),
                _fmt(dur.get("max")),
            ),
        ]
    linhas += [
        "== Fila arq (Redis) ==",
        f"max na fila (incl. debounce): {fila.max_zcard}",
        f"max prontos esperando worker: {fila.max_prontos}",
        f"max jobs em execucao: {fila.max_em_execucao}",
        f"esvaziou {_fmt(fila.esvaziou_em_s)} s apos o fim da carga",
        "== Worker ==",
        f"respostas enviadas: {tput.total}",
        f"throughput medio: {tput.media_por_min:.1f}/min  pico (60 s): {tput.pico_por_min}/min",
    ]
    p = percentis(latencias)
    linhas += [
        "== Ultima mensagem do cliente ate a resposta (s) ==",
        f"p50={_fmt(p[50], 2)} p95={_fmt(p[95], 2)} p99={_fmt(p[99], 2)} "
        f"max={_fmt(max(latencias, default=None), 2)}",
    ]
    return "\n".join(linhas)


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--k6-json", type=Path, required=True)
    ap.add_argument("--k6-resumo", type=Path, default=None)
    ap.add_argument("--stub-log", type=Path, required=True)
    ap.add_argument("--fila-csv", type=Path, required=True)
    ap.add_argument("--fim-carga", type=float, required=True, help="epoch do fim do k6")
    a = ap.parse_args(argv)
    with a.k6_json.open(encoding="utf-8") as f:
        mensagens = ler_mensagens_k6(f)
    envios = ler_envios_stub(a.stub_log)
    resumo = json.loads(a.k6_resumo.read_text()) if a.k6_resumo else None
    print(
        formatar(
            resumo,
            resumir_fila(ler_amostras(a.fila_csv), a.fim_carga),
            throughput([t for t, _ in envios]),
            latencias_resposta(mensagens, envios),
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
