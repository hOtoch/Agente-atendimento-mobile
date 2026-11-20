from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.domain.valores import Dinheiro

centavos = st.integers(min_value=-(10**9), max_value=10**9)


def din(c: int) -> Dinheiro:
    return Dinheiro.de(Decimal(c) / 100)


@given(centavos, centavos, centavos)
def test_soma_associativa_e_sem_perda(a: int, b: int, c: int) -> None:
    x, y, z = din(a), din(b), din(c)
    assert (x + y) + z == x + (y + z)
    assert (x + y + z).valor == Decimal(a + b + c) / 100


@given(centavos, centavos)
def test_subtracao_inversa_da_soma(a: int, b: int) -> None:
    x, y = din(a), din(b)
    assert (x + y) - y == x
    assert (x - y).valor == Decimal(a - b) / 100
    assert x - x == Dinheiro.zero()


@given(centavos, centavos)
def test_soma_comutativa(a: int, b: int) -> None:
    assert din(a) + din(b) == din(b) + din(a)


@pytest.mark.parametrize(
    ("entrada", "esperado"),
    [
        ("0.005", "0.01"),
        ("2.675", "2.68"),
        ("1.005", "1.01"),
        ("1.004", "1.00"),
        ("-0.005", "-0.01"),
        ("2310", "2310.00"),
    ],
)
def test_arredondamento_half_up(entrada: str, esperado: str) -> None:
    assert Dinheiro.de(Decimal(entrada)).valor == Decimal(esperado)
    # string "N.NNN" (N != 0) em pt-BR e milhar, entao so Decimal/virgula valem la
    if entrada not in {"2.675", "1.005", "1.004"}:
        assert Dinheiro.de(entrada).valor == Decimal(esperado)


@pytest.mark.parametrize(
    ("entrada", "esperado"),
    [
        ("2310", "2310.00"),
        (2310, "2310.00"),
        ("2.310,50", "2310.50"),
        ("R$ 2.310,50", "2310.50"),
        ("2310,5", "2310.50"),
        ("2310.50", "2310.50"),
        ("2.310", "2310.00"),
        ("0,005", "0.01"),
        ("2,675", "2.68"),
        ("1.234.567,89", "1234567.89"),
        ("-R$ 10,00", "-10.00"),
        ("-10", "-10.00"),
        (Decimal("4830"), "4830.00"),
    ],
)
def test_construtores(entrada: str | int | Decimal, esperado: str) -> None:
    assert Dinheiro.de(entrada).valor == Decimal(esperado)


def test_zero() -> None:
    assert Dinheiro.zero().valor == Decimal("0.00")
    assert Dinheiro.zero() == Dinheiro.de(0)


@pytest.mark.parametrize("ruim", ["", "abc", "1,2,3", "R$", "1.2.3"])
def test_string_invalida(ruim: str) -> None:
    with pytest.raises(ValueError):
        Dinheiro.de(ruim)


def test_float_rejeitado() -> None:
    with pytest.raises(TypeError):
        Dinheiro.de(1.5)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        Dinheiro.de(True)
    with pytest.raises(TypeError):
        Dinheiro.de(1) * 1.5  # type: ignore[operator]
    with pytest.raises(TypeError):
        Dinheiro.de(1) / 2.0  # type: ignore[operator]
    with pytest.raises(TypeError):
        Dinheiro.de(1) + 1  # type: ignore[operator]


def test_formatacao_ptbr() -> None:
    assert str(Dinheiro.de("2310")) == "R$ 2.310,00"
    assert str(Dinheiro.de("0.5")) == "R$ 0,50"
    assert str(Dinheiro.de("1234567.891")) == "R$ 1.234.567,89"
    assert str(Dinheiro.zero()) == "R$ 0,00"
    assert str(Dinheiro.de("-1500")) == "-R$ 1.500,00"


def test_multiplicacao() -> None:
    assert Dinheiro.de("4830") * Decimal("1.1054") == Dinheiro.de("5339.08")
    assert Decimal("0.5") * Dinheiro.de("101") == Dinheiro.de("50.50")
    assert Dinheiro.de("10.01") * 3 == Dinheiro.de("30.03")
    assert 3 * Dinheiro.de("10.01") == Dinheiro.de("30.03")


def test_divisao_por_int_com_arredondamento() -> None:
    assert Dinheiro.de("100") / 3 == Dinheiro.de("33.33")
    assert Dinheiro.de("200") / 3 == Dinheiro.de("66.67")
    assert Dinheiro.de("0.05") / 2 == Dinheiro.de("0.03")
    # exemplo do contexto: 4830 x 1,1054 / 12 = 444,92
    assert (Dinheiro.de("4830") * Decimal("1.1054")) / 12 == Dinheiro.de("444.92")
    with pytest.raises(ZeroDivisionError):
        Dinheiro.de(1) / 0


def test_comparacao_e_ordenacao() -> None:
    assert Dinheiro.de("1") < Dinheiro.de("2")
    assert Dinheiro.de("2") >= Dinheiro.de("2.00")
    assert max(Dinheiro.de("3"), Dinheiro.de("5")) == Dinheiro.de("5")
    assert sorted([Dinheiro.de("3"), Dinheiro.de("1")])[0] == Dinheiro.de("1")


def test_nao_negativo() -> None:
    assert Dinheiro.de("-5").nao_negativo() == Dinheiro.zero()
    assert Dinheiro.de("5").nao_negativo() == Dinheiro.de("5")
    assert Dinheiro.zero().nao_negativo() == Dinheiro.zero()


def test_predicados_e_neg() -> None:
    assert Dinheiro.de("-1").negativo
    assert not Dinheiro.zero().negativo
    assert Dinheiro.zero().zerado
    assert -Dinheiro.de("3") == Dinheiro.de("-3")
    assert abs(Dinheiro.de("-3")) == Dinheiro.de("3")


def test_somar_iteravel() -> None:
    assert Dinheiro.somar([Dinheiro.de("1"), Dinheiro.de("2.5")]) == Dinheiro.de("3.5")
    assert Dinheiro.somar([]) == Dinheiro.zero()


def test_imutavel_e_hashavel() -> None:
    d = Dinheiro.de("1")
    with pytest.raises(AttributeError):
        d.valor = Decimal("2")  # type: ignore[misc]
    assert {d, Dinheiro.de("1.00")} == {d}
