"""Capacidade de armazenamento e modelo de aparelho, com normalizacao tolerante."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Final, Self

_CAPACIDADE: Final = re.compile(r"(\d+(?:[.,]\d+)?)\s*(gb|g|tb|t)?")


class Capacidade(int):
    """Capacidade em GB inteiro (subclasse de int: ordenavel, hashavel, `== 1024`).

    `Capacidade("128GB")`, `Capacidade("128 gb")`, `Capacidade("64")` (sem unidade = GB),
    `Capacidade("1TB") == 1024`, `Capacidade(256)`. ValueError se invalida/<= 0;
    TypeError para float/bool. `str()` devolve "128GB" ou "1TB".
    """

    __slots__ = ()

    def __new__(cls, valor: str | int) -> Self:
        if isinstance(valor, bool) or not isinstance(valor, str | int):
            raise TypeError(f"Capacidade nao aceita {type(valor).__name__}")
        gb = valor if isinstance(valor, int) else cls._parse(valor)
        if gb <= 0:
            raise ValueError(f"capacidade deve ser positiva: {valor!r}")
        return super().__new__(cls, gb)

    @staticmethod
    def _parse(texto: str) -> int:
        casou = _CAPACIDADE.fullmatch(texto.strip().lower())
        if casou is None:
            raise ValueError(f"capacidade invalida: {texto!r}")
        try:
            numero = Decimal(casou.group(1).replace(",", "."))
        except InvalidOperation:  # pragma: no cover - regex ja garante
            raise ValueError(f"capacidade invalida: {texto!r}") from None
        gb = numero * 1024 if (casou.group(2) or "").startswith("t") else numero
        if gb != gb.to_integral_value():
            raise ValueError(f"capacidade nao inteira em GB: {texto!r}")
        return int(gb)

    def __str__(self) -> str:
        n = int(self)
        return f"{n // 1024}TB" if n % 1024 == 0 and n >= 1024 else f"{n}GB"

    def __repr__(self) -> str:
        return f"Capacidade({str(self)!r})"


_SE: Final = "iPhone SE (2ª ou 3ª geração)"

MODELOS_IPHONE: Final[tuple[str, ...]] = (
    "iPhone 8",
    "iPhone 8 Plus",
    "iPhone X",
    "iPhone XR",
    "iPhone XS",
    "iPhone XS Max",
    _SE,
    "iPhone 11",
    "iPhone 11 Pro",
    "iPhone 11 Pro Max",
    "iPhone 12 mini",
    "iPhone 12",
    "iPhone 12 Pro",
    "iPhone 12 Pro Max",
    "iPhone 13 mini",
    "iPhone 13",
    "iPhone 13 Pro",
    "iPhone 13 Pro Max",
    "iPhone 14",
    "iPhone 14 Plus",
    "iPhone 14 Pro",
    "iPhone 14 Pro Max",
    "iPhone 15",
    "iPhone 15 Plus",
    "iPhone 15 Pro",
    "iPhone 15 Pro Max",
    "iPhone 16e",
    "iPhone 16",
    "iPhone 16 Plus",
    "iPhone 16 Pro",
    "iPhone 16 Pro Max",
    "iPhone 17",
    "iPhone Air",
    "iPhone 17 Pro",
    "iPhone 17 Pro Max",
)
"""Nomes canonicos dos iPhones suportados (8 ate 17 Pro Max), em ordem de lancamento."""


def _chave(texto: str) -> str:
    """Forma comparavel: sem acento/caixa/separadores, sem prefixo 'iphone'/'apple'."""
    ascii_ = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode().lower()
    ascii_ = re.sub(r"[^a-z0-9]", "", ascii_.replace("+", "plus"))
    for prefixo in ("apple", "iphone"):
        ascii_ = ascii_.removeprefix(prefixo)
    return ascii_


_POR_CHAVE: Final[dict[str, str]] = {_chave(m): m for m in MODELOS_IPHONE if m != _SE}


def _canonico_iphone(texto: str) -> str | None:
    chave = _chave(texto)
    if chave.startswith("se"):
        return _SE
    return _POR_CHAVE.get(chave)


@dataclass(frozen=True, slots=True)
class ModeloAparelho:
    """Marca + nome normalizado do aparelho; comparavel e hashavel.

    Crie com `ModeloAparelho.de("iphone15 pro max")` -> nome "iPhone 15 Pro Max".
    Apple reconhecida vira o nome canonico de `MODELOS_IPHONE` (`conhecido=True`).
    Apple desconhecida ou outra marca: nome em title case, `conhecido=False`.
    """

    marca: str
    nome: str
    conhecido: bool = False

    @classmethod
    def de(cls, texto: str, marca: str = "Apple") -> ModeloAparelho:
        """Normaliza texto livre. ValueError se texto ou marca forem vazios."""
        marca_norm = " ".join(marca.split()).title()
        limpo = " ".join(texto.split())
        if not limpo or not marca_norm:
            raise ValueError("modelo e marca nao podem ser vazios")
        if marca_norm == "Apple":
            canonico = _canonico_iphone(limpo)
            if canonico is not None:
                return cls("Apple", canonico, True)
        return cls(marca_norm, limpo.title(), False)

    def __str__(self) -> str:
        return self.nome
