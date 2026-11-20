"""Value object monetario. Sempre Decimal com 2 casas, ROUND_HALF_UP; nunca float."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Final

_CENTAVO: Final = Decimal("0.01")
_MILHAR_PTBR: Final = re.compile(r"[1-9]\d{0,2}(\.\d{3})+")
_NUMERO: Final = re.compile(r"\d+(\.\d+)?")


def _arredondar(valor: Decimal) -> Decimal:
    return valor.quantize(_CENTAVO, rounding=ROUND_HALF_UP)


def _eh_inteiro(valor: object) -> bool:
    return isinstance(valor, int) and not isinstance(valor, bool)


def _parse_texto(texto: str) -> Decimal:
    bruto = texto.strip().replace("R$", "").replace(" ", "").replace(" ", "")
    negativo = bruto.startswith("-")
    bruto = bruto.lstrip("-")
    if "," in bruto:
        bruto = bruto.replace(".", "").replace(",", ".")
    elif _MILHAR_PTBR.fullmatch(bruto):
        bruto = bruto.replace(".", "")
    if not _NUMERO.fullmatch(bruto):
        raise ValueError(f"valor monetario invalido: {texto!r}")
    valor = Decimal(bruto)
    return -valor if negativo else valor


@dataclass(frozen=True, order=True, slots=True)
class Dinheiro:
    """Quantia em reais, imutavel, com 2 casas decimais (ROUND_HALF_UP).

    Construa com `Dinheiro.de(...)` ou `Dinheiro.zero()`. O construtor direto
    exige `Decimal` (que e arredondado para 2 casas). Float e rejeitado (TypeError).

    Operadores: `+`, `-` (entre Dinheiro), `*` por Decimal/int (inclusive `fator * d`),
    `/` por int (arredonda), `-d`, `abs(d)`, comparacoes e ordenacao.
    Para somar varios: `Dinheiro.somar(itens)`.
    """

    valor: Decimal

    def __post_init__(self) -> None:
        if not isinstance(self.valor, Decimal):
            raise TypeError(f"Dinheiro exige Decimal, recebeu {type(self.valor).__name__}")
        object.__setattr__(self, "valor", _arredondar(self.valor))

    @classmethod
    def de(cls, entrada: str | int | Decimal) -> Dinheiro:
        """Cria a partir de str, int ou Decimal. float/bool levantam TypeError.

        Strings aceitam pt-BR: "2.310,50", "R$ 2.310,50", "2310,5", "-10", e tambem
        "2310.50". Ponto sem virgula e milhar quando segue o padrao `N.NNN` com N != 0
        ("2.310" = 2310); caso contrario e decimal ("0.005", "2310.5").
        """
        if isinstance(entrada, Decimal):
            return cls(entrada)
        if isinstance(entrada, str):
            return cls(_parse_texto(entrada))
        if _eh_inteiro(entrada):
            return cls(Decimal(entrada))
        raise TypeError(f"Dinheiro.de nao aceita {type(entrada).__name__}")

    @classmethod
    def zero(cls) -> Dinheiro:
        return cls(Decimal(0))

    @classmethod
    def somar(cls, itens: Iterable[Dinheiro]) -> Dinheiro:
        """Soma um iteravel de Dinheiro (vazio resulta em zero)."""
        total = Decimal(0)
        for item in itens:
            total += item.valor
        return cls(total)

    @property
    def negativo(self) -> bool:
        return self.valor < 0

    @property
    def zerado(self) -> bool:
        return self.valor == 0

    def nao_negativo(self) -> Dinheiro:
        """`max(self, 0)`: valores negativos viram zero."""
        return Dinheiro.zero() if self.negativo else self

    def __add__(self, outro: object) -> Dinheiro:
        if not isinstance(outro, Dinheiro):
            return NotImplemented
        return Dinheiro(self.valor + outro.valor)

    def __sub__(self, outro: object) -> Dinheiro:
        if not isinstance(outro, Dinheiro):
            return NotImplemented
        return Dinheiro(self.valor - outro.valor)

    def __mul__(self, fator: object) -> Dinheiro:
        if isinstance(fator, Decimal):
            return Dinheiro(self.valor * fator)
        if _eh_inteiro(fator):
            return Dinheiro(self.valor * int(fator))  # type: ignore[call-overload]
        return NotImplemented

    __rmul__ = __mul__

    def __truediv__(self, divisor: object) -> Dinheiro:
        if not _eh_inteiro(divisor):
            return NotImplemented
        if divisor == 0:
            raise ZeroDivisionError("divisao de Dinheiro por zero")
        return Dinheiro(self.valor / int(divisor))  # type: ignore[call-overload]

    def __neg__(self) -> Dinheiro:
        return Dinheiro(-self.valor)

    def __abs__(self) -> Dinheiro:
        return Dinheiro(abs(self.valor))

    def __str__(self) -> str:
        """Formato pt-BR: `R$ 2.310,00` (negativo: `-R$ 1.500,00`)."""
        texto = f"{abs(self.valor):,.2f}".translate(str.maketrans(",.", ".,"))
        return f"{'-' if self.negativo else ''}R$ {texto}"

    def __repr__(self) -> str:
        return f"Dinheiro({self.valor})"
