"""Checagem pos-teste de carga: o que o k6 enviou x o que esta no banco.

    cd backend
    uv run python scripts/checar_contagem.py --k6-json ../infra/k6/saida/eventos.json \\
        --database-url postgresql+asyncpg://... --loja-id <uuid> --prefixo carga-

Compara os ids de WhatsApp unicos que o k6 mandou (metrica `msg_enviada`, uma por requisicao)
com `mensagens.id_externo` (`<loja>:<id>`) das mensagens de entrada. Falha (codigo 1) se:

- perdida: o webhook respondeu 2xx e a mensagem nao esta no banco;
- duplicada: o mesmo id aparece mais de uma vez no banco (inclusive apos reentrega);
- inesperada: ha no banco um id com o prefixo do teste que o k6 nunca enviou.

Requisicao sem 2xx (5xx, timeout) nao e perda: a Evolution reenviaria; fica em `rejeitadas`.
Tambem informa quantas conversas terminaram sem resposta (ultima mensagem e do cliente).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

METRICA = "msg_enviada"


@dataclass(frozen=True, slots=True)
class Envio:
    """Uma requisicao do k6 ao webhook."""

    id_wa: str
    status: int
    resultado: str


@dataclass(slots=True)
class Relatorio:
    requisicoes: int = 0
    enviados_unicos: int = 0
    reentregas: int = 0
    aceitos: int = 0
    no_banco: int = 0
    perdidas: list[str] = field(default_factory=list)
    duplicadas: list[str] = field(default_factory=list)
    inesperadas: list[str] = field(default_factory=list)
    rejeitadas: list[str] = field(default_factory=list)
    conversas_sem_resposta: int | None = None

    @property
    def ok(self) -> bool:
        return not (self.perdidas or self.duplicadas or self.inesperadas)


def _aceita(envio: Envio) -> bool:
    return 200 <= envio.status < 300


def comparar(envios: Iterable[Envio], ids_no_banco: Sequence[str]) -> Relatorio:
    lista = list(envios)
    enviados = {e.id_wa for e in lista}
    aceitos = {e.id_wa for e in lista if _aceita(e)}
    banco = Counter(ids_no_banco)
    r = Relatorio(
        requisicoes=len(lista),
        enviados_unicos=len(enviados),
        reentregas=len(lista) - len(enviados),
        aceitos=len(aceitos),
        no_banco=len(banco),
    )
    r.perdidas = sorted(aceitos - banco.keys())
    r.duplicadas = sorted(i for i, n in banco.items() if n > 1)
    r.inesperadas = sorted(banco.keys() - enviados)
    r.rejeitadas = sorted(enviados - aceitos - banco.keys())
    return r


def ler_eventos_k6(linhas: Iterable[str]) -> list[Envio]:
    """Le o NDJSON de `k6 --out json=...` e devolve um `Envio` por ponto de `msg_enviada`."""
    envios: list[Envio] = []
    for linha in linhas:
        linha = linha.strip()
        if not linha:
            continue
        try:
            evento = json.loads(linha)
        except ValueError:
            continue
        if evento.get("type") != "Point" or evento.get("metric") != METRICA:
            continue
        tags = evento.get("data", {}).get("tags", {})
        try:
            status = int(tags.get("status", 0))
        except (TypeError, ValueError):
            status = 0
        envios.append(
            Envio(
                id_wa=str(tags.get("id_wa", "")),
                status=status,
                resultado=str(tags.get("resultado", "")),
            )
        )
    return envios


def formatar(r: Relatorio) -> str:
    linhas = [
        f"requisicoes do k6 .......... {r.requisicoes}",
        f"ids unicos enviados ........ {r.enviados_unicos}",
        f"reentregas (mesmo id) ...... {r.reentregas}",
        f"ids aceitos (2xx) .......... {r.aceitos}",
        f"ids no banco ............... {r.no_banco}",
        f"rejeitadas (sem 2xx) ....... {len(r.rejeitadas)}",
        f"perdidas ................... {len(r.perdidas)}",
        f"duplicadas ................. {len(r.duplicadas)}",
        f"inesperadas ................ {len(r.inesperadas)}",
    ]
    if r.conversas_sem_resposta is not None:
        linhas.append(f"conversas sem resposta ..... {r.conversas_sem_resposta}")
    for nome, ids in (
        ("perdidas", r.perdidas),
        ("duplicadas", r.duplicadas),
        ("inesperadas", r.inesperadas),
    ):
        if ids:
            linhas.append(f"{nome}: {', '.join(ids[:20])}{' ...' if len(ids) > 20 else ''}")
    linhas.append(
        "RESULTADO: OK (nenhuma perdida, nenhuma duplicada)" if r.ok else "RESULTADO: FALHOU"
    )
    return "\n".join(linhas)


def executar(
    arquivo_k6: Path, ids_no_banco: Sequence[str], conversas_sem_resposta: int | None = None
) -> int:
    with arquivo_k6.open(encoding="utf-8") as f:
        envios = ler_eventos_k6(f)
    relatorio = comparar(envios, ids_no_banco)
    relatorio.conversas_sem_resposta = conversas_sem_resposta
    print(formatar(relatorio))
    return 0 if relatorio.ok else 1


async def ler_do_banco(database_url: str, loja_id: str, prefixo: str) -> tuple[list[str], int]:
    """`(ids de WhatsApp das mensagens de entrada, conversas cuja ultima mensagem e do cliente)`."""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    padrao = f"{loja_id}:{prefixo}%"
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as conn:
            linhas = await conn.execute(
                text(
                    "SELECT id_externo FROM mensagens "
                    "WHERE canal = 'whatsapp' AND direcao = 'entrada' AND id_externo LIKE :p"
                ),
                {"p": padrao},
            )
            ids = [str(i).split(":", 1)[1] for (i,) in linhas]
            sem_resposta = await conn.execute(
                text(
                    "SELECT count(*) FROM conversas c WHERE EXISTS ("
                    "  SELECT 1 FROM mensagens m WHERE m.conversa_id = c.id "
                    "AND m.id_externo LIKE :p"
                    ") AND (SELECT m2.direcao FROM mensagens m2 WHERE m2.conversa_id = c.id "
                    "       ORDER BY m2.criado_em DESC LIMIT 1) = 'entrada'"
                ),
                {"p": padrao},
            )
            return ids, int(sem_resposta.scalar_one())
    finally:
        await engine.dispose()


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--k6-json", type=Path, required=True, help="saida `k6 --out json=...`")
    p.add_argument("--database-url", required=True)
    p.add_argument("--loja-id", required=True)
    p.add_argument("--prefixo", required=True, help="prefixo dos ids de WhatsApp do teste")
    a = p.parse_args(argv)
    ids, sem_resposta = asyncio.run(ler_do_banco(a.database_url, a.loja_id, a.prefixo))
    return executar(a.k6_json, ids, sem_resposta)


if __name__ == "__main__":
    sys.exit(main())
