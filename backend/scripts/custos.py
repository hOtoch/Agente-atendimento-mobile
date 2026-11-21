# ruff: noqa: E501  (prosa do documento gerado em strings longas)
"""Custo por conversa a partir do usage registrado, e projecao para 1 mil / 10 mil leads por mes.

    cd backend
    uv run python scripts/custos.py --relatorios evals/relatorios/2026-11-21-real-*.json \
        --saida ../docs/custos.md
    uv run python scripts/custos.py --banco                  # usage real (eventos `llm_uso`)
    uv run python scripts/custos.py --banco postgresql+asyncpg://...   # outro banco

Duas fontes de usage: os relatorios JSON do eval (`evals/relatorios`) e a tabela `eventos`
(tipo `llm_uso`, somado por lead). Os precos por modelo vem de `evals/precos.py` (um lugar so, o
mesmo do eval); audio e infra sao PREMISSAS declaradas em `Premissas` e impressas no documento.
Nao chama nenhuma API paga: so le numeros ja registrados.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.application.llm import UsoTokens  # noqa: E402
from evals.precos import PRECOS, custo_usd  # noqa: E402

_USD2 = Decimal("0.01")
VOLUMES = (1_000, 10_000)

# Referencia historica medida no eval real do Sonnet 5.5 antes do cache incremental da conversa
# (commit 5a1145c): ~70 mil tokens de entrada sem cache por conversa.
SONNET_ANTES_DO_CACHE_INCREMENTAL_USD = Decimal("0.177")


class ModeloSemPreco(ValueError):
    """O usage traz um modelo que nao esta em `evals/precos.py`."""


@dataclass(frozen=True, slots=True)
class Premissas:
    """Tudo o que nao e medido e entra na projecao. Estimativas, a conferir com a loja real."""

    # Audio (STT na entrada do cliente, TTS na resposta da IA). Precos de referencia, a conferir.
    pct_conversas_com_audio: Decimal = Decimal("0.30")
    minutos_stt_por_conversa_com_audio: Decimal = Decimal("0.6")  # ~2 audios de ~18 s
    minutos_tts_por_conversa_com_audio: Decimal = Decimal("1.0")  # ~4 respostas de ~15 s
    usd_stt_por_minuto: Decimal = Decimal("0.003")  # gpt-4o-mini-transcribe
    usd_tts_por_minuto: Decimal = Decimal("0.015")  # gpt-4o-mini-tts
    # Infra em US$/mes (faixa min-max) por volume de leads/mes. context.md §6: 2 vCPU/4 GB
    # atende ate ~10 mil leads/mes; o limite superior do volume maior inclui folga de disco/banco.
    infra_usd_mes: dict[int, tuple[Decimal, Decimal]] = field(
        default_factory=lambda: {
            1_000: (Decimal(20), Decimal(50)),
            10_000: (Decimal(40), Decimal(100)),
        }
    )


@dataclass(frozen=True, slots=True)
class FonteEval:
    """Usage do agente, por cenario (= conversa), lido de um relatorio JSON do eval."""

    arquivo: str
    data: str
    modelo: str
    cenarios: int
    aprovados: int
    conversas: list[list[UsoTokens]]
    # (cenario, checagens que falharam) so dos cenarios reprovados
    falhas: tuple[tuple[str, tuple[str, ...]], ...] = ()


@dataclass(frozen=True, slots=True)
class TokensMedios:
    entrada: int
    saida: int
    cache_leitura: int
    cache_escrita: int


@dataclass(frozen=True, slots=True)
class Resumo:
    conversas: int
    media: Decimal
    p50: Decimal
    maximo: Decimal
    tokens_medios: TokensMedios


@dataclass(frozen=True, slots=True)
class Projecao:
    leads: int
    llm: Decimal
    audio: Decimal
    infra_min: Decimal
    infra_max: Decimal

    @property
    def total_min(self) -> Decimal:
        return self.llm + self.audio + self.infra_min

    @property
    def total_max(self) -> Decimal:
        return self.llm + self.audio + self.infra_max

    @property
    def por_lead_min(self) -> Decimal:
        return self.total_min / self.leads

    @property
    def por_lead_max(self) -> Decimal:
        return self.total_max / self.leads


# --- calculo ---------------------------------------------------------------------------------


def custo_conversa(usos: Sequence[UsoTokens]) -> Decimal:
    """US$ de uma conversa: soma do custo de cada modelo usado nela (fallback = 2 modelos)."""
    total = Decimal(0)
    for uso in usos:
        c = custo_usd(uso)
        if c is None:
            raise ModeloSemPreco(f"modelo sem preco cadastrado em evals/precos.py: {uso.modelo}")
        total += c
    return total


def resumir(conversas: Sequence[Sequence[UsoTokens]]) -> Resumo:
    if not conversas:
        raise ValueError("nenhuma conversa com usage para calcular")
    custos = [custo_conversa(c) for c in conversas]
    n = len(conversas)

    def media(campo: Callable[[UsoTokens], int]) -> int:
        return round(sum(campo(u) for c in conversas for u in c) / n)

    return Resumo(
        conversas=n,
        media=sum(custos, Decimal(0)) / n,
        p50=Decimal(statistics.median(custos)),
        maximo=max(custos),
        tokens_medios=TokensMedios(
            media(lambda u: u.entrada),
            media(lambda u: u.saida),
            media(lambda u: u.cache_leitura),
            media(lambda u: u.cache_escrita),
        ),
    )


def efeito_do_cache(conversas: Sequence[Sequence[UsoTokens]]) -> tuple[Decimal, Decimal]:
    """(custo medio com cache, custo medio se os tokens de cache fossem cobrados como entrada)."""
    com = resumir(conversas).media
    sem_cache = [
        [
            UsoTokens(u.modelo, u.entrada + u.cache_leitura + u.cache_escrita, u.saida, 0, 0)
            for u in c
        ]
        for c in conversas
    ]
    return com, resumir(sem_cache).media


def custo_audio_por_conversa(p: Premissas) -> Decimal:
    por_conversa_com_audio = (
        p.minutos_stt_por_conversa_com_audio * p.usd_stt_por_minuto
        + p.minutos_tts_por_conversa_com_audio * p.usd_tts_por_minuto
    )
    return p.pct_conversas_com_audio * por_conversa_com_audio


def projetar(custo_llm_por_conversa: Decimal, *, leads: int, premissas: Premissas) -> Projecao:
    """Custo mensal de `leads` conversas/mes (1 lead = 1 conversa). `KeyError` sem faixa de infra."""
    infra_min, infra_max = premissas.infra_usd_mes[leads]
    return Projecao(
        leads=leads,
        llm=(custo_llm_por_conversa * leads).quantize(_USD2, ROUND_HALF_UP),
        audio=(custo_audio_por_conversa(premissas) * leads).quantize(_USD2, ROUND_HALF_UP),
        infra_min=infra_min,
        infra_max=infra_max,
    )


# --- leitura do usage ------------------------------------------------------------------------


def _uso(d: dict[str, int | str]) -> UsoTokens:
    return UsoTokens(
        str(d["modelo"]),
        int(d["entrada"]),
        int(d["saida"]),
        int(d["cache_leitura"]),
        int(d["cache_escrita"]),
    )


def ler_relatorio_eval(caminho: Path) -> FonteEval:
    dados = json.loads(caminho.read_text(encoding="utf-8"))
    cenarios = dados["cenarios"]
    return FonteEval(
        arquivo=caminho.name,
        data=dados["data"],
        modelo=dados["modelo"],
        cenarios=int(dados.get("total_cenarios", len(cenarios))),
        aprovados=int(dados["aprovados"]),
        conversas=[[_uso(c["uso_agente"])] for c in cenarios],
        falhas=tuple(
            (
                c["id"],
                tuple(
                    k["nome"] for k in c.get("checagens", []) if k["aplicavel"] and not k["passou"]
                ),
            )
            for c in cenarios
            if not c["aprovado"] and not c.get("deve_reprovar")
        ),
    )


async def ler_usos_do_banco(database_url: str) -> list[list[UsoTokens]]:
    """Soma os eventos `llm_uso` por lead (uma conversa), separando por modelo."""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    consulta = text(
        """
        SELECT lead_id,
               payload->>'modelo' AS modelo,
               SUM((payload->>'entrada')::bigint) AS entrada,
               SUM((payload->>'saida')::bigint) AS saida,
               SUM((payload->>'cache_leitura')::bigint) AS cache_leitura,
               SUM((payload->>'cache_escrita')::bigint) AS cache_escrita
        FROM eventos
        WHERE tipo = 'llm_uso' AND lead_id IS NOT NULL
        GROUP BY lead_id, payload->>'modelo'
        ORDER BY lead_id, modelo
        """
    )
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as conn:
            linhas = (await conn.execute(consulta)).all()
    finally:
        await engine.dispose()
    por_lead: dict[object, list[UsoTokens]] = defaultdict(list)
    for lead_id, modelo, entrada, saida, cache_l, cache_e in linhas:
        por_lead[lead_id].append(
            UsoTokens(modelo, int(entrada), int(saida), int(cache_l), int(cache_e))
        )
    return list(por_lead.values())


# --- markdown --------------------------------------------------------------------------------


def _usd(v: Decimal, casas: int) -> str:
    """`US$ 1.234,57`: milhar com ponto e decimal com virgula (pt-BR)."""
    q = v.quantize(Decimal(1).scaleb(-casas), ROUND_HALF_UP)
    inteiro, _, frac = f"{q:,.{casas}f}".partition(".")
    return f"US$ {inteiro.replace(',', '.')},{frac}"


def _usd6(v: Decimal) -> str:
    return _usd(v, 6)


def _usd2(v: Decimal) -> str:
    return _usd(v, 2)


def _usd3(v: Decimal) -> str:
    return _usd(v, 3)


def _faixa(a: Decimal, b: Decimal) -> str:
    return f"{_usd2(a)} a {_usd2(b)}"


def _milhar(n: int) -> str:
    return f"{n:,}".replace(",", ".")


def _melhor_por_modelo(fontes: Sequence[FonteEval]) -> list[FonteEval]:
    """Um relatorio por modelo (o mais recente por data e nome), do mais barato ao mais caro."""
    por_modelo: dict[str, FonteEval] = {}
    for f in sorted(fontes, key=lambda f: (f.data, f.arquivo)):
        por_modelo[f.modelo] = f
    return sorted(
        por_modelo.values(), key=lambda f: PRECOS[f.modelo].saida if f.modelo in PRECOS else 0
    )


def _rotulo(modelo: str) -> str:
    return modelo.removeprefix("claude-").replace("-5-5", " 5.5").capitalize()


def _decimal_ptbr(v: Decimal) -> str:
    return f"{v.normalize():f}".replace(".", ",")


def _secao_medido(escolhidas: Sequence[FonteEval], resumos: dict[str, Resumo]) -> list[str]:
    L = [
        "## Custo medido por conversa (agente)",
        "",
        "| Modelo | Relatório | Cenários | Aprovados | Média | p50 | Máximo |",
        "|---|---|---|---|---|---|---|",
    ]
    for f in escolhidas:
        r = resumos[f.modelo]
        L.append(
            f"| `{f.modelo}` | `{f.arquivo}` | {f.cenarios} | {f.aprovados}/{f.cenarios} "
            f"| {_usd6(r.media)} | {_usd6(r.p50)} | {_usd6(r.maximo)} |"
        )
    L += [
        "",
        "Só o agente: o cliente simulado do eval (Haiku, ~US$ 0,0004 por conversa) não existe em",
        "produção. Tokens médios do agente por conversa:",
        "",
        "| Modelo | Entrada (sem cache) | Saída | Cache lido | Cache escrito |",
        "|---|---|---|---|---|",
    ]
    for f in escolhidas:
        t = resumos[f.modelo].tokens_medios
        L.append(
            f"| `{f.modelo}` | {_milhar(t.entrada)} | {_milhar(t.saida)} "
            f"| {_milhar(t.cache_leitura)} | {_milhar(t.cache_escrita)} |"
        )
    return L


def _secao_cache(escolhidas: Sequence[FonteEval], resumos: dict[str, Resumo]) -> list[str]:
    L = [
        "## Efeito do cache de prompt",
        "",
        "O prefixo da chamada (ferramentas, system e a conversa até ali) se repete a cada chamada ao",
        "LLM; por isso quase toda a entrada é lida do cache (5% do preço da entrada no Sonnet, 10% no",
        "Haiku). Custo medido contra o mesmo usage cobrado como entrada comum:",
        "",
        "| Modelo | Com cache (medido) | Se não houvesse cache | Economia |",
        "|---|---|---|---|",
    ]
    for f in escolhidas:
        com, sem = efeito_do_cache(f.conversas)
        economia = (1 - com / sem) * 100 if sem else Decimal(0)
        L.append(f"| `{f.modelo}` | {_usd6(com)} | {_usd6(sem)} | {economia:.0f}% |")
    if any(f.modelo == "claude-sonnet-5-5" for f in escolhidas):
        agora = resumos["claude-sonnet-5-5"].media
        antes = SONNET_ANTES_DO_CACHE_INCREMENTAL_USD
        L += [
            "",
            "Antes e depois do cache incremental da conversa (commit `5a1145c`), Sonnet 5.5: cerca de",
            f"{_usd6(antes)} por conversa antes (~70 mil tokens de entrada sem cache) e {_usd6(agora)}",
            f"depois, ~{(1 - agora / antes) * 100:.0f}% menos. O valor de antes é a medição histórica do",
            "eval daquele dia; o relatório correspondente não está versionado.",
        ]
    return L


def _secao_projecao(
    escolhidas: Sequence[FonteEval], resumos: dict[str, Resumo], p: Premissas
) -> list[str]:
    L = [
        "## Projeção mensal (1 lead = 1 conversa)",
        "",
        "LLM = custo medido por conversa x leads. Áudio e infra são estimativas (ver Premissas);",
        "o total é uma faixa por causa da infra.",
        "",
        "| Volume | Modelo | LLM | Áudio (STT+TTS) | Infra | Total | Por lead |",
        "|---|---|---|---|---|---|---|",
    ]
    for leads in VOLUMES:
        for f in escolhidas:
            proj = projetar(resumos[f.modelo].media, leads=leads, premissas=p)
            L.append(
                f"| {_milhar(leads // 1000)} mil leads/mês | {_rotulo(f.modelo)} "
                f"| {_usd2(proj.llm)} | {_usd2(proj.audio)} "
                f"| {_faixa(proj.infra_min, proj.infra_max)} "
                f"| **{_faixa(proj.total_min, proj.total_max)}** "
                f"| {_usd3(proj.por_lead_min)} a {_usd3(proj.por_lead_max)} |"
            )
    return L


TRAVAS_DE_NEGOCIO = (
    "sem_valor_antes_da_proposta",
    "valores_vindos_de_ferramenta",
    "desconto_dentro_do_teto",
)


def _falhas_texto(f: FonteEval) -> str:
    itens = [f"`{c}` (checagem `{'`, `'.join(n)}`)" for c, n in f.falhas]
    return ", ".join(itens) if itens else "nenhuma"


def _secao_leitura(
    escolhidas: Sequence[FonteEval], resumos: dict[str, Resumo], p: Premissas
) -> list[str]:
    haiku = next((f for f in escolhidas if f.modelo == "claude-haiku-5-5"), None)
    sonnet = next((f for f in escolhidas if f.modelo == "claude-sonnet-5-5"), None)
    if haiku is None or sonnet is None:
        return []
    r_haiku, r_sonnet = resumos[haiku.modelo], resumos[sonnet.modelo]
    razao = r_sonnet.media / r_haiku.media
    travas_ok = not any(n in TRAVAS_DE_NEGOCIO for _, ns in haiku.falhas for n in ns)
    L = [
        "## Leitura e recomendação",
        "",
        f"- **Haiku 5.5 como modelo principal.** Passou {haiku.aprovados} de {haiku.cenarios} cenários do eval "
        f"a {_usd6(r_haiku.media)} por conversa, cerca de 1/{razao:.0f} do custo do Sonnet 5.5. "
        f"Reprovações: {_falhas_texto(haiku)}."
        + (
            " As travas de negócio (valor só de ferramenta, desconto no teto) passaram em todos os cenários."
            if travas_ok
            else ""
        ),
        f"- **Sonnet 5.5 como reserva ou opção de qualidade.** O eval real dele cobriu só {sonnet.cenarios} "
        f"cenários ({sonnet.aprovados}/{sonnet.cenarios} aprovados; reprovações: {_falhas_texto(sonnet)}): "
        "amostra pequena demais para dizer que é melhor ou pior. Para comparar de igual para igual, "
        f"rodar os mesmos {haiku.cenarios} cenários custaria cerca de {_usd2(r_sonnet.media * haiku.cenarios)} "
        "(eval real é pago: só com autorização).",
    ]
    audio = custo_audio_por_conversa(p)
    if audio >= r_haiku.media:
        L.append(
            f"- **Com Haiku, o áudio pesa mais que o LLM.** Nas premissas abaixo o STT+TTS custa {_usd6(audio)} "
            f"por conversa, contra {_usd6(r_haiku.media)} do modelo; desligar o TTS (opcional por loja) "
            "é a principal alavanca de custo."
        )
    return L + [""]


def _secao_premissas(p: Premissas) -> list[str]:
    L = [
        "## Premissas (estimativas, a validar com a operação real)",
        "",
        f"- **Áudio:** {p.pct_conversas_com_audio * 100:.0f}% das conversas têm áudio; nelas, "
        f"{_decimal_ptbr(p.minutos_stt_por_conversa_com_audio)} min de áudio do cliente (STT) e "
        f"{_decimal_ptbr(p.minutos_tts_por_conversa_com_audio)} min de resposta falada (TTS).",
        "- **Preço do áudio** (referência, conferir em <https://openai.com/api/pricing>): STT "
        f"US$ {_decimal_ptbr(p.usd_stt_por_minuto)}/min (`gpt-4o-mini-transcribe`), TTS "
        f"US$ {_decimal_ptbr(p.usd_tts_por_minuto)}/min (`gpt-4o-mini-tts`); média de "
        f"{_usd6(custo_audio_por_conversa(p))} por conversa. O TTS é opcional por loja.",
    ]
    for leads in VOLUMES:
        lo, hi = p.infra_usd_mes[leads]
        L.append(
            f"- **Infra com {_milhar(leads // 1000)} mil leads/mês:** {_faixa(lo, hi)} por mês "
            "(VPS, disco e backup; `context.md` §6: 2 vCPU/4 GB atendem até ~10 mil leads/mês)."
        )
    L += [
        "- **Black Friday:** 4 vCPU/8 GB, Postgres gerenciado e 2+ workers custam mais e não estão "
        "nessas faixas.",
        "- **Fora da conta:** WhatsApp (Evolution self-hosted não cobra por mensagem; a API oficial "
        "cobra templates de follow-up), domínio, monitoramento e mão de obra.",
        "- **Amostra:** a média vem do eval (conversas roteirizadas); conversas reais mais curtas ou "
        "mais longas mudam o custo na mesma proporção. Use `--banco` para recalcular com conversas "
        "reais.",
    ]
    return L


def gerar_markdown(
    fontes: Sequence[FonteEval],
    premissas: Premissas,
    *,
    banco: Sequence[Sequence[UsoTokens]] | None = None,
) -> str:
    escolhidas = _melhor_por_modelo(fontes)
    resumos = {f.modelo: resumir(f.conversas) for f in escolhidas}
    referencia = max(f.data for f in escolhidas)
    L = [
        "# Custos",
        "",
        f"Gerado por `backend/scripts/custos.py` a partir dos relatórios do eval de {referencia}. "
        "Valores em US$. O custo de LLM é **medido** (usage registrado); áudio e infraestrutura são "
        "**estimativas** com premissas explícitas. Preços por modelo (US$ por milhão de tokens) em "
        "`backend/evals/precos.py`.",
        "",
    ]
    L += _secao_medido(escolhidas, resumos) + [""]
    L += _secao_cache(escolhidas, resumos) + [""]
    L += _secao_projecao(escolhidas, resumos, premissas) + [""]
    L += _secao_leitura(escolhidas, resumos, premissas)
    L += _secao_premissas(premissas)
    if banco:
        r = resumir(banco)
        L += [
            "",
            "## Conversas reais (banco)",
            "",
            f"{r.conversas} conversas com `llm_uso`: média {_usd6(r.media)}, p50 {_usd6(r.p50)}, "
            f"máximo {_usd6(r.maximo)}.",
        ]
    L += [
        "",
        "## Como regenerar",
        "",
        "```bash",
        "cd backend",
        "uv run python scripts/custos.py \\",
        "  --relatorios evals/relatorios/2026-11-21-real-claude-haiku-5-5.json \\",
        "  --relatorios evals/relatorios/2026-11-21-real-claude-sonnet-5-5.json \\",
        "  --saida ../docs/custos.md",
        "```",
        "",
        "Para números novos, rode o eval real (pago, só com autorização) e aponte o script para o "
        "relatório gerado; ou use `--banco` para somar os eventos `llm_uso` das conversas reais "
        '(a seção "Conversas reais" entra no documento).',
        "",
    ]
    return "\n".join(L)


# --- CLI -------------------------------------------------------------------------------------


def _args(argv: Sequence[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Custo por conversa e projecao 1k/10k leads por mes.")
    p.add_argument(
        "--relatorios",
        action="append",
        nargs="+",
        default=[],
        metavar="JSON",
        help="relatorio(s) JSON do eval (repetivel)",
    )
    p.add_argument(
        "--banco",
        nargs="?",
        const="",
        default=None,
        metavar="DATABASE_URL",
        help="le o usage real dos eventos llm_uso (sem valor: usa DATABASE_URL do ambiente)",
    )
    p.add_argument("--saida", type=Path, help="grava o markdown aqui (padrao: stdout)")
    return p.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _args(argv)
    arquivos = [Path(a) for grupo in args.relatorios for a in grupo]
    if not arquivos and args.banco is None:
        print("informe --relatorios <json>... e/ou --banco", file=sys.stderr)
        return 2
    try:
        fontes = [ler_relatorio_eval(a) for a in arquivos]
        banco: list[list[UsoTokens]] | None = None
        if args.banco is not None:
            url = args.banco or _database_url()
            banco = asyncio.run(ler_usos_do_banco(url))
        if not fontes:
            if not banco:
                print("nenhum evento llm_uso no banco", file=sys.stderr)
                return 1
            r = resumir(banco)
            print(
                f"{r.conversas} conversas: media {_usd6(r.media)}, p50 {_usd6(r.p50)}, "
                f"maximo {_usd6(r.maximo)}"
            )
            return 0
        md = gerar_markdown(fontes, Premissas(), banco=banco)
    except (ModeloSemPreco, ValueError, OSError, KeyError) as exc:
        print(f"erro: {exc}", file=sys.stderr)
        return 1
    if args.saida:
        args.saida.write_text(md, encoding="utf-8")
        print(f"gerado {args.saida}")
    else:
        print(md)
    return 0


def _database_url() -> str:
    from app.infra.settings import get_settings  # noqa: PLC0415

    return get_settings().database_url


if __name__ == "__main__":
    raise SystemExit(main())
