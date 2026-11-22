"""Texto da pergunta "como voce prefere pagar?" montado so com as formas que a loja aceita.

Duas vozes: a instrucao para o LLM na mensagem de estado do turno e a frase sugerida ao cliente
que volta nas ferramentas. Sem `formas` (None), todas as quatro formas, como antes da config.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from app.domain.ficha import TipoPagamento
from app.domain.formas_pagamento import FormasAceitas

_TODAS: Final = FormasAceitas(pix=True, debito=True, credito=True, entrada_mais_credito=True)

ROTULOS_INSTRUCAO: Final[dict[TipoPagamento, str]] = {
    TipoPagamento.PIX: "Pix",
    TipoPagamento.DEBITO: "débito",
    TipoPagamento.CREDITO: "crédito",
    TipoPagamento.ENTRADA_MAIS_CREDITO: "entrada mais cartão",
}

_ROTULOS_CLIENTE: Final[dict[TipoPagamento, str]] = {
    **ROTULOS_INSTRUCAO,
    TipoPagamento.CREDITO: "cartão de crédito",
}


def _ou(itens: Sequence[str]) -> str:
    """`A`, `A ou B`, `A, B ou C`."""
    if len(itens) <= 1:
        return "".join(itens)
    return f"{', '.join(itens[:-1])} ou {itens[-1]}"


def rotulos_aceitos(formas: FormasAceitas) -> list[str]:
    return [ROTULOS_INSTRUCAO[t] for t in formas.tipos()]


def instrucao_pergunta_pagamento(formas: FormasAceitas | None) -> str:
    """Instrucao ao LLM (mensagem de estado) para perguntar a forma de pagamento."""
    aceitos = rotulos_aceitos(formas or _TODAS)
    if not aceitos:
        return (
            "A loja não tem forma de pagamento configurada: não prometa nenhuma e chame "
            "chamar_vendedor."
        )
    if len(aceitos) == 1:
        return (
            f"A loja só aceita {aceitos[0]}: confirme se ele paga assim, "
            "sem oferecer outras formas."
        )
    return f"Pergunte como ele prefere pagar: {_ou(aceitos)}."


def pergunta_pagamento_ao_cliente(formas: FormasAceitas | None) -> str:
    """Frase sugerida ao cliente (resultado das ferramentas)."""
    tipos = (formas or _TODAS).tipos()
    nomes = [_ROTULOS_CLIENTE[t] for t in tipos]
    if not nomes:
        return "Vou chamar um vendedor para combinar o pagamento com você."
    if len(nomes) == 1:
        return f"A loja aceita apenas {nomes[0]}: tudo bem pagar assim?"
    return f"Como você prefere pagar: {_ou(nomes)}?"
