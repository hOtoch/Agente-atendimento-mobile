import pytest

from app.domain.valores import Bandeira


@pytest.mark.parametrize(
    ("texto", "esperada"),
    [
        ("Master", Bandeira.MASTERCARD),
        ("MASTERCARD", Bandeira.MASTERCARD),
        ("master card", Bandeira.MASTERCARD),
        ("mastercard", Bandeira.MASTERCARD),
        ("Visa", Bandeira.VISA),
        (" VISA ", Bandeira.VISA),
        ("Elo", Bandeira.ELO),
        ("Hipercard", Bandeira.HIPERCARD),
        ("Hiper", Bandeira.HIPERCARD),
        ("Amex", Bandeira.AMEX),
        ("American Express", Bandeira.AMEX),
    ],
)
def test_parse_tolerante(texto: str, esperada: Bandeira) -> None:
    assert Bandeira.parse(texto) is esperada


def test_valores_do_enum() -> None:
    assert [b.value for b in Bandeira] == ["mastercard", "visa", "elo", "hipercard", "amex"]
    assert Bandeira("visa") is Bandeira.VISA


@pytest.mark.parametrize("ruim", ["", "dinners", "pix"])
def test_parse_invalida(ruim: str) -> None:
    with pytest.raises(ValueError):
        Bandeira.parse(ruim)
