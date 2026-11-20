"""Bandeiras de cartao."""

from __future__ import annotations

import re
import unicodedata
from enum import StrEnum
from typing import Final


class Bandeira(StrEnum):
    """Bandeira do cartao. O valor (str) e o identificador estavel."""

    MASTERCARD = "mastercard"
    VISA = "visa"
    ELO = "elo"
    HIPERCARD = "hipercard"
    AMEX = "amex"

    @classmethod
    def parse(cls, texto: str) -> Bandeira:
        """Interpreta texto livre ("Master", "MASTERCARD", "American Express").

        Levanta ValueError se nao reconhecer.
        """
        sem_acento = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
        chave = re.sub(r"[^a-z]", "", sem_acento.lower())
        try:
            return _ALIASES[chave]
        except KeyError:
            raise ValueError(f"bandeira desconhecida: {texto!r}") from None


_ALIASES: Final[dict[str, Bandeira]] = {
    "master": Bandeira.MASTERCARD,
    "mastercard": Bandeira.MASTERCARD,
    "mc": Bandeira.MASTERCARD,
    "visa": Bandeira.VISA,
    "elo": Bandeira.ELO,
    "hiper": Bandeira.HIPERCARD,
    "hipercard": Bandeira.HIPERCARD,
    "amex": Bandeira.AMEX,
    "americanexpress": Bandeira.AMEX,
}
