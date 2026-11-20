"""Executor do eval.

    cd backend
    uv run python -m evals.rodar --modo fake          # CI: agente roteirizado, sem custo
    uv run python -m evals.rodar --modo real --modelo claude-sonnet-5-5 \\
        [--modelo-cliente claude-haiku-5-5] [--cenarios a,b] --confirmo-custo   # PAGO

O modo real imprime a estimativa de custo e, sem `--confirmo-custo`, sai com codigo 3 sem
chamar nenhuma API. Codigos de saida: 0 ok, 1 algum cenario fora do esperado, 2 uso invalido
(ou sem chave), 3 falta confirmar o custo.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Callable, Sequence
from datetime import date
from pathlib import Path

from app.application.llm import LLMPort
from evals.cenarios import CENARIOS, CONTROLES
from evals.cliente import ClienteLLM
from evals.conversa import ResultadoCenario, rodar_cenario, rodar_cenario_fake
from evals.modelos import Cenario
from evals.precos import PRECOS, estimar_custo
from evals.relatorio import montar_dados, montar_markdown, para_json
from evals.roteiros import ROTEIROS_FAKE

MODELO_CLIENTE_PADRAO = "claude-haiku-5-5"
SAIDA_PADRAO = Path(__file__).resolve().parent / "relatorios"

FabricaLLM = Callable[[str], LLMPort]


class ChaveAusente(Exception):
    pass


def _fabrica_real(modelo: str) -> LLMPort:
    from app.infra.llm import criar_llm
    from app.infra.settings import get_settings

    settings = get_settings()
    if not settings.anthropic_api_key:
        raise ChaveAusente("ANTHROPIC_API_KEY nao configurada (defina no .env ou no ambiente)")
    # sem modelo reserva: o eval mede o modelo pedido, nao um fallback
    return criar_llm(settings.model_copy(update={"llm_model": modelo, "llm_fallback_model": ""}))


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m evals.rodar", description=__doc__.split("\n")[0])
    p.add_argument("--modo", choices=["fake", "real"], default="fake")
    p.add_argument("--modelo", help="modelo do agente (modo real)")
    p.add_argument("--modelo-cliente", default=MODELO_CLIENTE_PADRAO)
    p.add_argument("--cenarios", help="ids separados por virgula (padrao: todos)")
    p.add_argument("--confirmo-custo", action="store_true", help="autoriza gastar (modo real)")
    p.add_argument("--saida", type=Path, default=SAIDA_PADRAO, help="pasta dos relatorios")
    p.add_argument("--data", default=None, help="AAAA-MM-DD do relatorio (padrao: hoje)")
    return p


def _escolher(ids: str | None, base: Sequence[Cenario]) -> list[Cenario] | str:
    if not ids:
        return list(base)
    por_id = {c.id: c for c in base}
    pedidos = [i.strip() for i in ids.split(",") if i.strip()]
    ruins = [i for i in pedidos if i not in por_id]
    if ruins:
        return "cenario(s) desconhecido(s) neste modo: " + ", ".join(ruins)
    return [por_id[i] for i in pedidos]


def _imprimir_estimativa(modelo: str, cliente: str, cenarios: Sequence[Cenario]) -> None:
    turnos = max(c.max_turnos for c in cenarios)
    est = estimar_custo(modelo, cliente, cenarios=len(cenarios), turnos=turnos)
    print("Estimativa de custo (teto, modo real)")
    print(f"  cenarios: {len(cenarios)} x turnos maximos: {turnos}")
    print(f"  agente  ({modelo}): US$ {est.agente:.2f}")
    print(f"  cliente ({cliente}): US$ {est.cliente:.2f}")
    print(f"  total estimado: US$ {est.total:.2f}")
    print("  premissas: tokens medios por turno em evals/precos.py; o custo real sai no relatorio.")


def main(argv: Sequence[str] | None = None, *, fabrica_llm: FabricaLLM | None = None) -> int:
    args = _parser().parse_args(argv)
    data = args.data or date.today().isoformat()

    if args.modo == "fake":
        escolha = _escolher(args.cenarios, [*CENARIOS, *CONTROLES])
        if isinstance(escolha, str):
            print(escolha, file=sys.stderr)
            return 2
        sem_roteiro = [c.id for c in escolha if c.id not in ROTEIROS_FAKE]
        if args.cenarios and sem_roteiro:
            print("sem roteiro no modo fake: " + ", ".join(sem_roteiro), file=sys.stderr)
            return 2
        cenarios = [c for c in escolha if c.id in ROTEIROS_FAKE]
        resultados = asyncio.run(_rodar_fake(cenarios))
        modelo, modelo_cliente = "fake", None
    else:
        if not args.modelo:
            print("o modo real exige --modelo <id>", file=sys.stderr)
            return 2
        for m in (args.modelo, args.modelo_cliente):
            if m not in PRECOS:
                print(f"modelo sem preço cadastrado em evals/precos.py: {m}", file=sys.stderr)
                return 2
        escolha = _escolher(args.cenarios, CENARIOS)
        if isinstance(escolha, str):
            print(escolha, file=sys.stderr)
            return 2
        _imprimir_estimativa(args.modelo, args.modelo_cliente, escolha)
        if not args.confirmo_custo:
            print(
                "\nNada foi executado. Para rodar de verdade (pago), repita com --confirmo-custo."
            )
            return 3
        fabrica = fabrica_llm or _fabrica_real
        try:
            llm_agente = fabrica(args.modelo)
            llm_cliente = fabrica(args.modelo_cliente)
        except ChaveAusente as exc:
            print(str(exc), file=sys.stderr)
            return 2
        resultados = asyncio.run(_rodar_real(escolha, llm_agente, llm_cliente))
        modelo, modelo_cliente = args.modelo, args.modelo_cliente

    dados = montar_dados(
        resultados, data=data, modo=args.modo, modelo=modelo, modelo_cliente=modelo_cliente
    )
    args.saida.mkdir(parents=True, exist_ok=True)
    base = args.saida / f"{data}-{args.modo}-{modelo}"
    base.with_suffix(".md").write_text(montar_markdown(dados, resultados), encoding="utf-8")
    base.with_suffix(".json").write_text(para_json(dados), encoding="utf-8")

    fora = [r.cenario.id for r in resultados if r.aprovado == r.cenario.deve_reprovar]
    print(
        f"{dados['aprovados']}/{dados['total_cenarios']} cenarios aprovados; relatorio: {base}.md"
    )
    if fora:
        print("fora do esperado: " + ", ".join(fora), file=sys.stderr)
        return 1
    return 0


async def _rodar_fake(cenarios: Sequence[Cenario]) -> list[ResultadoCenario]:
    return [await rodar_cenario_fake(c) for c in cenarios]


async def _rodar_real(
    cenarios: Sequence[Cenario], llm_agente: LLMPort, llm_cliente: LLMPort
) -> list[ResultadoCenario]:
    return [await rodar_cenario(c, llm_agente, ClienteLLM(llm_cliente, c)) for c in cenarios]


if __name__ == "__main__":
    raise SystemExit(main())
