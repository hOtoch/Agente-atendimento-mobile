"""Conversao tolerante de valores de celula (texto livre digitado pela loja)."""

from __future__ import annotations

import re
import unicodedata
from decimal import Decimal, InvalidOperation
from typing import Any

_MILHAR = re.compile(r"^\d{1,3}(\.\d{3})+$")
_SIM = {"sim", "s", "yes", "y", "true", "verdadeiro", "1"}
_NAO = {"nao", "n", "no", "false", "falso", "0"}


class CelulaInvalida(ValueError):
    """Valor de celula que nao da para interpretar (a mensagem ja e amigavel)."""


def sem_acento(texto: str) -> str:
    return unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()


def normalizar(texto: object) -> str:
    """Minusculo, sem acento e com espacos colapsados (para comparar cabecalhos e perguntas)."""
    base = sem_acento(str(texto)).lower()
    return " ".join(re.sub(r"[^a-z0-9%+]+", " ", base).split())


def vazio(valor: Any) -> bool:
    return valor is None or (isinstance(valor, str) and not valor.strip())


def texto(valor: Any) -> str:
    return "" if valor is None else str(valor).strip()


def eh_sem(valor: Any) -> bool:
    return isinstance(valor, str) and valor.strip().lower() == "sem"


def eh_igual(valor: Any) -> bool:
    return isinstance(valor, str) and valor.strip().lower() == "igual"


def para_decimal(valor: Any) -> Decimal:
    """Aceita 10,54 | R$ 3.100 | 3.100,50 | 2500.5 | 5% (o % e ignorado)."""
    if isinstance(valor, bool):
        raise CelulaInvalida(f"Valor inválido: {valor!r}.")
    if isinstance(valor, int):
        return Decimal(valor)
    if isinstance(valor, float):
        return Decimal(str(valor))
    bruto = texto(valor)
    limpo = re.sub(r"(?i)r\$|%|\s", "", bruto)
    if "," in limpo:
        limpo = limpo.replace(".", "").replace(",", ".")
    elif _MILHAR.match(limpo):
        limpo = limpo.replace(".", "")
    try:
        numero = Decimal(limpo)
    except InvalidOperation:
        raise CelulaInvalida(
            f"Valor inválido: {bruto!r}. Use um número, como 3100 ou 3.100,00."
        ) from None
    if not numero.is_finite():
        raise CelulaInvalida(f"Valor inválido: {bruto!r}. Use um número, como 3100 ou 3.100,00.")
    return numero


def para_int(valor: Any, rotulo: str = "número inteiro") -> int:
    try:
        numero = para_decimal(valor)
    except CelulaInvalida:
        raise CelulaInvalida(f"Valor inválido: {texto(valor)!r}. Use um {rotulo}.") from None
    if numero != numero.to_integral_value():
        raise CelulaInvalida(f"Valor inválido: {texto(valor)!r}. Use um {rotulo}.")
    return int(numero)


def para_capacidade(valor: Any) -> int:
    """Aceita 128 | '128GB' | '1TB' | '1 tb' (resultado em GB)."""
    erro = CelulaInvalida(
        f"Capacidade inválida: {texto(valor)!r}. Use um número em GB, como 128 ou 1TB."
    )
    if isinstance(valor, bool):
        raise erro
    if isinstance(valor, (int, float)):
        numero = Decimal(str(valor))
        multiplicador = 1
    else:
        m = re.fullmatch(r"\s*([\d.,]+)\s*(gb|g|tb|t)?\s*", texto(valor).lower())
        if m is None:
            raise erro
        try:
            numero = para_decimal(m.group(1))
        except CelulaInvalida:
            raise erro from None
        multiplicador = 1024 if m.group(2) in ("tb", "t") else 1
    gb = numero * multiplicador
    if gb != gb.to_integral_value() or gb <= 0:
        raise erro
    return int(gb)


def para_bool(valor: Any) -> bool:
    if isinstance(valor, bool):
        return valor
    chave = normalizar(valor)
    if chave in _SIM:
        return True
    if chave in _NAO:
        return False
    raise CelulaInvalida(f"Resposta inválida: {texto(valor)!r}. Responda sim ou não.")
