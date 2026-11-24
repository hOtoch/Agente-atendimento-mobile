"""parece_aceite: o cliente aceitou a ficha (e nao perguntou nem pediu desconto ou mudanca)."""

from __future__ import annotations

import pytest

from app.application.agente.aceite import parece_aceite


@pytest.mark.parametrize(
    "fala",
    [
        "sim", "Sim!", "SIM", "isso", "pode", "pode fechar", "Fechado", "fechado, pode ser assim!",
        "confirmo", "certo", "correto", "beleza", "bora", "ok", "OK!", "perfeito", "show", "👍",
        "Sim, tá tudo certo", "pode confirmar", "está correto sim", "sím", "isso mesmo", "✅",
    ],
)  # fmt: skip
def test_aceites(fala: str) -> None:
    assert parece_aceite(fala)


@pytest.mark.parametrize(
    "fala",
    [
        "", "oi", "quanto fica em 10x?", "quanto fica em 10x", "tem desconto?", "não",
        "nao, errado",
        "sim mas queria desconto", "quero mais desconto", "pode ser em 12x", "e se for no pix?",
        "qual o endereço", "ok, mas tem brinde?", "sim, não precisa de mais nada",
        "mudar para pix", "pode dar uma capinha de brinde", "beleza, e a bateria?",
        "sim\nquanto custa o frete?", "tá caro, abaixa um pouco",
    ],
)  # fmt: skip
def test_nao_aceites(fala: str) -> None:
    assert not parece_aceite(fala)
