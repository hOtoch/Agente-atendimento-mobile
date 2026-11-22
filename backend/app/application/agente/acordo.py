"""Fechamento do acordo: o snapshot gravado no estado e o que a IA repassa ao cliente.

Tudo aqui e deterministico: os valores vem da `ultima_proposta` (calculada pelo dominio), a
forma de pagamento vem da ficha e endereco, horarios e chave Pix vem da config da loja. A IA so
repassa o que `conteudo_para_ia` devolve; nunca inventa nada disso.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, date, datetime
from typing import Any

from app.application.agente.estado import EstadoAtendimento, descrever_troca
from app.application.config.modelos import PagamentoLoja, PerfilLoja
from app.domain.ficha import TipoPagamento

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


def conteudo_para_ia(acordo: Mapping[str, Any], tipo: TipoPagamento) -> dict[str, Any]:
    """O retorno da ferramenta: o que a IA deve dizer ao cliente (sem inventar nada)."""
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
    conteudo["mensagem"] = (
        f"Acordo fechado. Envie ao cliente, nesta mesma resposta, {envio}, exatamente como "
        "devolvidos aqui. Depois agradeça a preferência e chame chamar_vendedor com motivo "
        f"'{MOTIVO_ACORDO_FECHADO}' (avise, em uma frase, que um vendedor conclui o atendimento "
        "na loja)."
    )
    return conteudo
