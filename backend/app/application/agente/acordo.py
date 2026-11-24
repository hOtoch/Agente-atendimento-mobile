"""Fechamento do acordo: o snapshot gravado no estado e o que a IA repassa ao cliente.

Tudo aqui e deterministico: os valores vem da `ultima_proposta` (calculada pelo dominio), a
forma de pagamento vem da ficha e endereco, horarios e chave Pix vem da config da loja. A IA so
repassa o que `conteudo_para_ia` devolve; nunca inventa nada disso.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import UTC, date, datetime
from typing import Any

from app.application.agente.estado import EstadoAtendimento, descrever_troca
from app.application.config.modelos import PagamentoLoja, PerfilLoja
from app.domain.ficha import TipoPagamento
from app.domain.valores import Dinheiro

MOTIVO_ACORDO_FECHADO = "acordo_fechado"

_PIX_NA_LOJA = (
    "A loja não cadastrou chave Pix: avise o cliente que o vendedor passa os dados do Pix na loja. "
    "Nunca tente inventar chave nem favorecido."
)
_SEM_ENDERECO = (
    "A loja não cadastrou o endereço: avise que o vendedor passa o endereço em seguida. "
    "Nunca tente inventar."
)


def formatar_horarios(horarios: Mapping[str, str]) -> str:
    """`seg: 09:00-18:00; sab: 09:00-14:00` (vazio se a loja nao informou)."""
    return "; ".join(f"{dia}: {faixa}" for dia, faixa in horarios.items())


def paga_via_pix(tipo: TipoPagamento) -> bool:
    """Pix, ou entrada de entrada + cartao (a entrada e paga na loja/Pix)."""
    return tipo in (TipoPagamento.PIX, TipoPagamento.ENTRADA_MAIS_CREDITO)


def _chave_pix(tipo: TipoPagamento, pagamento: PagamentoLoja) -> dict[str, str] | None:
    chave = pagamento.chave_pix
    if chave is None or not paga_via_pix(tipo) or not pagamento.formas.pix:
        return None
    return {"tipo": chave.tipo.value, "chave": chave.chave, "favorecido": chave.favorecido}


def montar_acordo(
    estado: EstadoAtendimento,
    proposta: Mapping[str, Any],
    *,
    perfil: PerfilLoja | None,
    pagamento: PagamentoLoja,
    fechado_em: datetime,
) -> dict[str, Any]:
    """Snapshot do acordo (so tipos JSON). Precisa da ficha completa e da proposta vigente."""
    ficha = estado.ficha
    p = ficha.pagamento
    assert p.tipo is not None, "ficha completa tem forma de pagamento"
    data = ficha.data_prevista_compra
    desconto = proposta.get("desconto") or {}
    troca = dict(proposta.get("troca") or {})
    troca["aparelho_usado"] = descrever_troca(estado) if ficha.tem_troca else None
    return {
        "fechado_em": fechado_em.astimezone(UTC).isoformat(),
        "aparelho": dict(proposta.get("aparelho") or {}),
        "preco_aparelho": proposta.get("preco_aparelho"),
        "troca": troca,
        "desconto": {k: desconto.get(k) for k in ("negociado", "oportunidade_unica", "total")},
        "desconto_liberado": str(estado.desconto.liberado),
        "forma_escolhida": dict(proposta.get("forma_escolhida") or {}),
        "pagamento": {
            "tipo": p.tipo.value,
            "parcelas": p.parcelas,
            "bandeira": None if p.bandeira is None else p.bandeira.value,
            "entrada": None if p.entrada is None else str(p.entrada),
        },
        "data_prevista": None if data is None else data.isoformat(),
        "informado": {
            "endereco": perfil.endereco if perfil else None,
            "horarios": formatar_horarios(perfil.horarios) if perfil else None,
            "chave_pix": _chave_pix(p.tipo, pagamento),
        },
    }


def mesmo_acordo(a: Mapping[str, Any] | None, b: Mapping[str, Any]) -> bool:
    """Igual ignorando a hora do fechamento (chamar de novo nao muda nada)."""
    if a is None:
        return False
    return {k: v for k, v in a.items() if k != "fechado_em"} == {
        k: v for k, v in b.items() if k != "fechado_em"
    }


def _data_br(iso: str | None) -> str | None:
    return None if iso is None else date.fromisoformat(iso).strftime("%d/%m/%Y")


_DIAS = {
    "seg": "segunda",
    "ter": "terça",
    "qua": "quarta",
    "qui": "quinta",
    "sex": "sexta",
    "sab": "sábado",
    "dom": "domingo",
}
_ORDEM_DIAS = list(_DIAS)
_FAIXA = re.compile(r"^(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})$")


def _hora(h: str, m: str) -> str:
    return f"{int(h)}h" if m == "00" else f"{int(h)}h{m}"


def _faixa_legivel(faixa: str) -> str:
    casou = _FAIXA.match(faixa.strip())
    if casou is None:
        return faixa.strip()
    h1, m1, h2, m2 = casou.groups()
    return f"das {_hora(h1, m1)} às {_hora(h2, m2)}"


def _dias_legiveis(dias: list[str]) -> str:
    nomes = [_DIAS.get(d, d) for d in dias]
    if len(nomes) == 1:
        return nomes[0]
    if len(nomes) == 2:
        return f"{nomes[0]} e {nomes[1]}"
    return f"{nomes[0]} a {nomes[-1]}"


def horarios_legiveis(horarios: str | None) -> str | None:
    """`seg: 09:00-18:00; ...; sab: 09:00-14:00` -> `Segunda a sexta, das 9h às 18h; sábado, ...`.

    Junta dias seguidos com a mesma faixa. O que nao estiver no formato padrao sai como veio.
    """
    if not horarios or not horarios.strip():
        return None
    itens: list[tuple[str, str]] = []
    for item in horarios.split(";"):
        dia, sep, faixa = item.partition(":")
        if sep:
            itens.append((dia.strip(), faixa.strip()))
    # o banco pode devolver os dias fora de ordem (jsonb reordena as chaves): ordem da semana
    fim = len(_ORDEM_DIAS)
    itens.sort(key=lambda par: _ORDEM_DIAS.index(par[0]) if par[0] in _ORDEM_DIAS else fim)
    grupos: list[tuple[list[str], str]] = []
    for dia, faixa in itens:
        anterior = grupos[-1] if grupos else None
        seguido = (
            anterior is not None
            and anterior[1] == faixa
            and dia in _ORDEM_DIAS
            and anterior[0][-1] in _ORDEM_DIAS
            and _ORDEM_DIAS.index(dia) == _ORDEM_DIAS.index(anterior[0][-1]) + 1
        )
        if anterior is not None and seguido:
            anterior[0].append(dia)
        else:
            grupos.append(([dia], faixa))
    if not grupos:
        return None
    texto = "; ".join(f"{_dias_legiveis(d)}, {_faixa_legivel(f)}" for d, f in grupos)
    return texto[0].upper() + texto[1:]


def _bandeira(acordo: Mapping[str, Any]) -> str:
    bandeira = (acordo.get("pagamento") or {}).get("bandeira")
    return f" {str(bandeira).title()}" if bandeira else ""


def _valor_na_forma(acordo: Mapping[str, Any], tipo: TipoPagamento) -> str:
    forma = acordo["forma_escolhida"]
    bandeira = _bandeira(acordo)
    if tipo is TipoPagamento.PIX:
        return f"{forma['valor_a_vista']} à vista no Pix"
    if tipo is TipoPagamento.DEBITO:
        return f"{forma['total_pago']} no débito{bandeira}"
    parcelado = f"{forma['parcelas']}x de {forma['valor_parcela']} no cartão{bandeira}"
    if tipo is TipoPagamento.ENTRADA_MAIS_CREDITO:
        parcelado = f"entrada de {forma['entrada']} + {parcelado}"
    return f"{parcelado} (total {forma['total_pago']})"


def _aparelho(acordo: Mapping[str, Any]) -> str:
    ap = acordo["aparelho"]
    texto = f"{ap['modelo']} {ap['condicao']} de {ap['capacidade']}"
    return f"{texto}, cor {str(ap['cor']).lower()}" if ap.get("cor") else texto


def _valores(acordo: Mapping[str, Any], tipo: TipoPagamento, desconto: str | None = None) -> str:
    """Primeiro o que o usado vale na troca, depois o valor final (ja com a troca descontada)."""
    troca = acordo.get("troca") or {}
    usado = troca.get("aparelho_usado")
    valor = _valor_na_forma(acordo, tipo)
    linha_desconto = [] if desconto is None else [f"Desconto: {desconto}"]
    if troca.get("status") == "avaliada":
        return "\n".join(
            [
                f"Seu {usado} na troca: {troca['valor']}",
                *linha_desconto,
                f"Valor final, já descontada a troca: {valor}",
            ]
        )
    if troca.get("status") == "avaliacao_na_loja":
        return "\n".join(
            [
                f"Seu {usado} será avaliado na loja; o valor abaixo não inclui a troca.",
                *linha_desconto,
                f"Valor final: {valor}",
            ]
        )
    return "\n".join([*linha_desconto, f"Valor final: {valor}"])


OBSERVACAO_PRE_AVALIACAO = (
    "Obs.: esta é uma pré-avaliação; o valor final é confirmado na loja com o aparelho em mãos."
)


def mensagem_fechamento(acordo: Mapping[str, Any], tipo: TipoPagamento) -> str:
    """A mensagem que vai ao cliente quando o acordo fecha: valor, Pix, endereco e horarios.

    Montada pelo codigo (nada de valor ou dado da loja escrito pelo modelo), em paragrafos e com
    poucos emojis. So usa o que esta no acordo; o que a loja nao cadastrou vira aviso. A
    observacao de pre-avaliacao fecha a mensagem.
    """
    informado = acordo["informado"]
    paragrafos = [
        f"Fechado! 🎉 Resumo do seu pedido: {_aparelho(acordo)}.",
        _valores(acordo, tipo),
    ]

    if paga_via_pix(tipo):
        chave = informado["chave_pix"]
        if chave is None:
            paragrafos.append("O vendedor passa os dados do Pix na loja.")
        else:
            alvo = "a entrada " if tipo is TipoPagamento.ENTRADA_MAIS_CREDITO else ""
            paragrafos.append(
                f"Para pagar {alvo}no Pix:\nChave: {chave['chave']}\n"
                f"Favorecido: {chave['favorecido']}"
            )

    loja: list[str] = []
    if informado["endereco"]:
        loja.append(f"📍 {informado['endereco']}")
    else:
        loja.append("O vendedor te passa o endereço da loja em seguida.")
    horarios = horarios_legiveis(informado["horarios"])
    if horarios:
        loja.append(f"🕘 {horarios}")
    paragrafos.append("\n".join(loja))

    paragrafos.append(
        "Obrigado pela preferência! Um vendedor vai continuar o atendimento com você na loja."
    )
    paragrafos.append(OBSERVACAO_PRE_AVALIACAO)
    return "\n\n".join(paragrafos)


def ficha_confirmacao(
    estado: EstadoAtendimento,
    proposta: Mapping[str, Any],
    *,
    desconto_conseguido: str | None = None,
) -> str:
    """A ficha que o cliente confere ANTES de fechar: aparelho, troca, desconto, valor final.

    Montada pelo codigo, no mesmo estilo de `mensagem_fechamento`: so a forma de pagamento
    escolhida (nunca as alternativas) e nenhum valor fora da proposta. `desconto_conseguido` e o
    valor liberado agora (primeiro degrau pedido antes da ficha, ou um pedido na negociacao).
    """
    ficha = estado.ficha
    tipo = ficha.pagamento.tipo
    assert tipo is not None, "ficha completa tem forma de pagamento"
    troca = dict(proposta.get("troca") or {})
    troca["aparelho_usado"] = descrever_troca(estado) if ficha.tem_troca else None
    visao = {
        "aparelho": proposta.get("aparelho") or {},
        "forma_escolhida": proposta.get("forma_escolhida") or {},
        "troca": troca,
        "pagamento": {
            "bandeira": None if ficha.pagamento.bandeira is None else ficha.pagamento.bandeira.value
        },
    }
    desconto = (proposta.get("desconto") or {}).get("total")
    tem_desconto = isinstance(desconto, str) and desconto != str(Dinheiro.zero())
    paragrafos = ["Confere seu pedido:"]
    if desconto_conseguido is not None:
        paragrafos.append(f"Consegui um desconto de {desconto_conseguido} para você.")
    paragrafos.append(f"{_aparelho(visao)}.")
    paragrafos.append(_valores(visao, tipo, desconto if tem_desconto else None))
    data = ficha.data_prevista_compra
    if data is not None:
        paragrafos.append(f"Data prevista da compra: {data.strftime('%d/%m/%Y')}")
    paragrafos.append(OBSERVACAO_PRE_AVALIACAO)
    paragrafos.append("Está tudo certo para eu confirmar seu pedido?")
    return "\n\n".join(paragrafos)


def conteudo_para_ia(acordo: Mapping[str, Any], tipo: TipoPagamento) -> dict[str, Any]:
    """O retorno da ferramenta: os dados do acordo e a mensagem pronta que o sistema envia."""
    informado = acordo["informado"]
    chave = informado["chave_pix"]
    envio = "o endereço e os horários da loja"
    conteudo: dict[str, Any] = {
        "status": "ok",
        "acordo_fechado": True,
        "aparelho": acordo["aparelho"],
        "forma_escolhida": acordo["forma_escolhida"],
        "data_prevista": _data_br(acordo["data_prevista"]),
        "endereco": informado["endereco"],
        "horarios": informado["horarios"],
    }
    if informado["endereco"] is None:
        conteudo["instrucao_endereco"] = _SEM_ENDERECO
    if paga_via_pix(tipo):
        if chave is not None:
            conteudo["pix"] = chave
            alvo = "da entrada" if tipo is TipoPagamento.ENTRADA_MAIS_CREDITO else "do pagamento"
            envio += f", mais a chave Pix e o favorecido {alvo}"
        else:
            conteudo["instrucao_pix"] = _PIX_NA_LOJA
    conteudo["mensagem_ao_cliente"] = mensagem_fechamento(acordo, tipo)
    conteudo["mensagem"] = (
        f"Acordo fechado. O sistema envia ao cliente a mensagem_ao_cliente ({envio}, o valor "
        "final e o agradecimento) como a resposta deste turno: não reescreva esses dados. Agora "
        f"chame chamar_vendedor com motivo '{MOTIVO_ACORDO_FECHADO}'."
    )
    return conteudo
