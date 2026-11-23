"""Limpeza deterministica do texto que o modelo devolve antes de ir ao cliente."""

from __future__ import annotations

import pytest

from app.application.agente.texto_resposta import sem_repeticao, uma_pergunta

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


# --- uma pergunta por mensagem -------------------------------------------------------------


def test_pergunta_reescrita_numa_segunda_linha_sai_e_fica_so_a_primeira() -> None:
    """Caso real (gpt-4.1-mini): a mesma pergunta duas vezes, com palavras diferentes."""
    texto = (
        "Temos iPhone 15 Pro seminovo com 128GB, 256GB e 512GB de armazenamento. "
        "Qual dessas capacidades você prefere?\n"
        "Qual capacidade você prefere para o iPhone 15 Pro seminovo: 128GB, 256GB ou 512GB?"
    )
    assert uma_pergunta(texto) == (
        "Temos iPhone 15 Pro seminovo com 128GB, 256GB e 512GB de armazenamento. "
        "Qual dessas capacidades você prefere?"
    )


def test_segunda_pergunta_em_outro_paragrafo_tambem_sai() -> None:
    texto = "Anotado! Você tem aparelho para dar na troca?\n\nE quando pretende comprar?"
    assert uma_pergunta(texto) == "Anotado! Você tem aparelho para dar na troca?"


def test_linhas_sem_pergunta_depois_da_pergunta_ficam() -> None:
    texto = "Qual cor você prefere?\n\nTodas com garantia de 90 dias."
    assert uma_pergunta(texto) == texto


def test_lista_antes_da_pergunta_fica_inteira() -> None:
    texto = "Temos:\n- 128GB\n- 256GB\nQual você prefere?"
    assert uma_pergunta(texto) == texto


def test_texto_sem_pergunta_ou_com_uma_so_nao_muda() -> None:
    for texto in ("Fechado! 🎉\n\nObrigado pela preferência!", "Oi! Qual modelo você procura?"):
        assert uma_pergunta(texto) == texto
