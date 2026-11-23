"""Limpeza deterministica do texto que o modelo devolve antes de ir ao cliente."""

from __future__ import annotations

import pytest

from app.application.agente.texto_resposta import sem_repeticao

FRASE = "Você não vai dar aparelho usado na troca. Quando pretende fazer a compra?"


@pytest.mark.parametrize(
    "texto",
    [
        f"{FRASE}\n{FRASE}",
        f"{FRASE}\n\n{FRASE}",
        f"{FRASE} {FRASE}",
        f"{FRASE}\n{FRASE}\n{FRASE}",
    ],
)
def test_texto_repetido_pelo_modelo_sai_uma_vez_so(texto: str) -> None:
    assert sem_repeticao(texto) == FRASE


def test_linha_repetida_em_sequencia_some_e_o_resto_fica() -> None:
    texto = "Temos duas opções:\n- iPhone 15 novo\n- iPhone 15 novo\n- iPhone 15 seminovo"
    assert sem_repeticao(texto) == "Temos duas opções:\n- iPhone 15 novo\n- iPhone 15 seminovo"


def test_texto_sem_repeticao_nao_muda() -> None:
    texto = "Oi! Qual modelo você procura?\n\nTemos iPhone e Samsung."
    assert sem_repeticao(texto) == texto


def test_linha_igual_mas_nao_seguida_fica() -> None:
    texto = "Pix\nCartão\nPix"
    assert sem_repeticao(texto) == texto
