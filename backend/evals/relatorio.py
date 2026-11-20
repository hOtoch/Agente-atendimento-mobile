"""Relatorio do eval: dados agregados (JSON) e markdown, a partir dos `ResultadoCenario`."""

from __future__ import annotations

import json
import statistics
from decimal import Decimal
from typing import Any

from app.application.llm import UsoTokens
from evals.checagens import NOMES_CHECAGENS
from evals.conversa import ResultadoCenario
from evals.modelos import ExecucaoFerramenta, MensagemAgente, MensagemCliente
from evals.precos import custo_usd

_CASAS = Decimal("0.000001")


def _usd(valor: Decimal | None) -> str | None:
    return None if valor is None else str(valor.quantize(_CASAS))


def _estatisticas(valores: list[Decimal]) -> dict[str, str | None]:
    if not valores:
        return {"media": None, "p50": None, "maximo": None}
    return {
        "media": _usd(sum(valores, Decimal(0)) / len(valores)),
        "p50": _usd(Decimal(statistics.median(valores))),
        "maximo": _usd(max(valores)),
    }


def _uso(u: UsoTokens) -> dict[str, Any]:
    return {
        "modelo": u.modelo,
        "entrada": u.entrada,
        "saida": u.saida,
        "cache_leitura": u.cache_leitura,
        "cache_escrita": u.cache_escrita,
    }


def _linha(r: ResultadoCenario) -> dict[str, Any]:
    c_ag, c_cli = custo_usd(r.uso_agente), custo_usd(r.uso_cliente)
    total = None if c_ag is None else c_ag + (c_cli or Decimal(0))
    return {
        "id": r.cenario.id,
        "titulo": r.cenario.titulo,
        "aprovado": r.aprovado,
        "deve_reprovar": r.cenario.deve_reprovar,
        "como_esperado": r.aprovado != r.cenario.deve_reprovar,
        "erro": r.erro,
        "turnos": r.turnos,
        "etapa_final": r.transcricao.etapa_final,
        "handoff": r.transcricao.handoff,
        "checagens": [
            {"nome": c.nome, "passou": c.passou, "aplicavel": c.aplicavel, "motivo": c.motivo}
            for c in r.checagens
        ],
        "uso_agente": _uso(r.uso_agente),
        "uso_cliente": _uso(r.uso_cliente),
        "custo_agente_usd": _usd(c_ag),
        "custo_cliente_usd": _usd(c_cli),
        "custo_total_usd": _usd(total),
    }


def montar_dados(
    resultados: list[ResultadoCenario],
    *,
    data: str,
    modo: str,
    modelo: str,
    modelo_cliente: str | None,
) -> dict[str, Any]:
    """Estrutura do relatorio (JSON). `taxa_aprovacao` considera so os cenarios reais;
    os controles negativos entram a parte (`controles_como_esperado`)."""
    reais = [r for r in resultados if not r.cenario.deve_reprovar]
    controles = [r for r in resultados if r.cenario.deve_reprovar]
    aprovados = sum(r.aprovado for r in reais)
    agentes = [c for r in resultados if (c := custo_usd(r.uso_agente)) is not None]
    clientes = [c for r in resultados if (c := custo_usd(r.uso_cliente)) is not None]
    totais = [
        c + (custo_usd(r.uso_cliente) or Decimal(0))
        for r in resultados
        if (c := custo_usd(r.uso_agente)) is not None
    ]
    n = len(resultados) or 1
    return {
        "data": data,
        "modo": modo,
        "modelo": modelo,
        "modelo_cliente": modelo_cliente,
        "total_cenarios": len(reais),
        "aprovados": aprovados,
        "taxa_aprovacao": round(aprovados / len(reais), 4) if reais else None,
        "controles_total": len(controles),
        "controles_como_esperado": sum(not r.aprovado for r in controles),
        "cenarios": [_linha(r) for r in resultados],
        "custo": {
            "moeda": "USD",
            "por_conversa_agente": _estatisticas(agentes),
            "por_conversa_cliente": _estatisticas(clientes),
            "por_conversa_total": _estatisticas(totais),
        },
        "tokens_medios": {
            "entrada": round(sum(r.uso_agente.entrada for r in resultados) / n),
            "saida": round(sum(r.uso_agente.saida for r in resultados) / n),
            "cache_leitura": round(sum(r.uso_agente.cache_leitura for r in resultados) / n),
            "cache_escrita": round(sum(r.uso_agente.cache_escrita for r in resultados) / n),
        },
    }


def para_json(dados: dict[str, Any]) -> str:
    return json.dumps(dados, ensure_ascii=False, indent=2) + "\n"


def _celula(c: dict[str, Any] | None) -> str:
    if c is None or not c["aplicavel"]:
        return "–"
    return "✅" if c["passou"] else "❌"


def _transcricao_md(r: ResultadoCenario) -> list[str]:
    linhas = ["```"]
    for e in r.transcricao.eventos:
        if isinstance(e, MensagemCliente):
            linhas.append(f"cliente> {e.texto}")
        elif isinstance(e, MensagemAgente):
            linhas.append(f"agente > {e.texto}")
        elif isinstance(e, ExecucaoFerramenta):
            resumo = json.dumps(e.resultado, ensure_ascii=False)
            resumo = resumo if len(resumo) <= 160 else resumo[:159] + "…"
            marca = " [ERRO]" if e.erro else ""
            linhas.append(f"  ferramenta {e.nome}{marca} -> {resumo}")
    linhas.append("```")
    return linhas


def _custo_md(valor: str | None) -> str:
    return "n/d" if valor is None else f"US$ {valor}"


def montar_markdown(dados: dict[str, Any], resultados: list[ResultadoCenario]) -> str:
    titulo = f"# Eval de conversas: {dados['data']} ({dados['modo']}, {dados['modelo']})"
    out = [titulo, ""]
    if dados["modo"] == "fake":
        out += [
            "> Modo fake: agente roteirizado (FakeLLM) com ferramentas e loja demo reais. "
            "Valida o harness e as checagens; NAO mede a qualidade de nenhum modelo.",
            "",
        ]
    taxa = dados["taxa_aprovacao"]
    out += [
        f"**Taxa de aprovação:** {dados['aprovados']}/{dados['total_cenarios']}"
        + ("" if taxa is None else f" ({taxa * 100:.0f}%)"),
        "",
    ]
    if dados["controles_total"]:
        out += [
            f"**Controles negativos reprovados como esperado:** "
            f"{dados['controles_como_esperado']}/{dados['controles_total']}",
            "",
        ]
    cabecalho = ["Cenário", *NOMES_CHECAGENS, "Resultado"]
    out.append("| " + " | ".join(cabecalho) + " |")
    out.append("|" + "---|" * len(cabecalho))
    for linha in dados["cenarios"]:
        por_nome = {c["nome"]: c for c in linha["checagens"]}
        if linha["erro"]:
            resultado = "💥 erro"
        elif linha["deve_reprovar"]:
            resultado = "✅ reprovou (esperado)" if not linha["aprovado"] else "❌ devia reprovar"
        else:
            resultado = "✅ aprovado" if linha["aprovado"] else "❌ reprovado"
        celulas = [_celula(por_nome.get(n)) for n in NOMES_CHECAGENS]
        out.append(f"| `{linha['id']}` | " + " | ".join(celulas) + f" | {resultado} |")
    out.append("")

    custo, tok = dados["custo"], dados["tokens_medios"]
    out += ["## Custo medido por conversa", ""]
    out.append("| | média | p50 | máximo |")
    out.append("|---|---|---|---|")
    for rotulo, chave in (
        ("Agente", "por_conversa_agente"),
        ("Cliente simulado", "por_conversa_cliente"),
        ("Total", "por_conversa_total"),
    ):
        e = custo[chave]
        out.append(
            f"| {rotulo} | {_custo_md(e['media'])} | {_custo_md(e['p50'])} "
            f"| {_custo_md(e['maximo'])} |"
        )
    out += [
        "",
        f"Tokens médios do agente por conversa: entrada {tok['entrada']}, saída {tok['saida']}, "
        f"cache lido {tok['cache_leitura']}, cache escrito {tok['cache_escrita']}.",
        "",
    ]

    falhas = [r for r in resultados if not r.aprovado]
    if falhas:
        out += ["## Transcrições dos cenários que falharam", ""]
        for r in falhas:
            controle = " (controle negativo: falha esperada)" if r.cenario.deve_reprovar else ""
            out += [f"### `{r.cenario.id}`{controle}", ""]
            if r.erro:
                out += [f"Erro de execução: `{r.erro}`", ""]
            for c in r.checagens:
                if c.aplicavel and not c.passou:
                    out.append(f"- **{c.nome}**: {c.motivo}")
            out.append("")
            out += _transcricao_md(r)
            out.append("")
    return "\n".join(out)
