"""Taxas da maquininha (%), 1x a 18x e debito, para as 5 bandeiras."""

from decimal import Decimal

from app.application.config.entradas import EntradaTaxa
from app.domain.bandeira import Bandeira

# Mastercard: valores oficiais do exemplo (1x ... 18x).
MASTERCARD_CREDITO: tuple[str, ...] = (
    "3.44", "4.65", "5.44", "6.36", "7.15", "7.99", "9.33", "9.34", "9.58",
    "9.59", "10.53", "10.54", "12.69", "13.44", "14.19", "14.94", "15.03", "15.04",
)  # fmt: skip
MASTERCARD_DEBITO = "1.49"

# Acrescimo (pontos percentuais) sobre a Mastercard; None = "igual" (usa a Mastercard).
ACRESCIMO_POR_BANDEIRA: dict[Bandeira, Decimal | None] = {
    Bandeira.MASTERCARD: Decimal(0),
    Bandeira.VISA: None,
    Bandeira.ELO: Decimal("0.60"),
    Bandeira.HIPERCARD: Decimal("1.10"),
    Bandeira.AMEX: Decimal("1.60"),
}


def _taxas() -> tuple[EntradaTaxa, ...]:
    base: list[tuple[int | str, Decimal]] = [
        (n, Decimal(t)) for n, t in enumerate(MASTERCARD_CREDITO, start=1)
    ]
    base.append(("debito", Decimal(MASTERCARD_DEBITO)))
    entradas: list[EntradaTaxa] = []
    for bandeira, acrescimo in ACRESCIMO_POR_BANDEIRA.items():
        for chave, taxa in base:
            valor = None if acrescimo is None else taxa + acrescimo
            entradas.append(EntradaTaxa(chave, bandeira.value, valor))
    return tuple(entradas)


TAXAS: tuple[EntradaTaxa, ...] = _taxas()
