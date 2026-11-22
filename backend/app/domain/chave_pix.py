"""Chave Pix da loja (tipo, chave e favorecido), validada e normalizada no dominio.

Normalizacao: CPF e CNPJ so com os caracteres da chave (sem pontuacao), e-mail em minusculas,
telefone no formato do Pix (`+55` + DDD + numero) e chave aleatoria (UUID) em minusculas.
Dominio puro: sem IO.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

_FAVORECIDO_MAX: Final = 100
_EMAIL_MAX: Final = 77  # limite da chave de e-mail no Pix
_EMAIL: Final = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(\.[A-Za-z0-9\-]+)+$")
_ALEATORIA: Final = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE
)
_CNPJ: Final = re.compile(r"^[0-9A-Z]{12}[0-9]{2}$")
_PESOS_CNPJ: Final = (6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2)  # 13 pesos; o 1o DV usa os 12 ultimos


class TipoChavePix(StrEnum):
    CPF = "cpf"
    CNPJ = "cnpj"
    EMAIL = "email"
    TELEFONE = "telefone"
    ALEATORIA = "aleatoria"


@dataclass(frozen=True, slots=True)
class ChavePix:
    tipo: TipoChavePix
    chave: str
    """Ja normalizada (ver o docstring do modulo)."""
    favorecido: str


class ChavePixInvalida(Exception):
    """Erros por campo (`tipo`, `chave`, `favorecido`), todos de uma vez."""

    def __init__(self, erros: list[tuple[str, str]]) -> None:
        super().__init__("; ".join(f"{campo}: {mensagem}" for campo, mensagem in erros))
        self.erros: tuple[tuple[str, str], ...] = tuple(erros)


def montar_chave_pix(tipo: str, chave: str, favorecido: str) -> ChavePix:
    """Valida e normaliza; levanta `ChavePixInvalida` com os erros por campo."""
    erros: list[tuple[str, str]] = []
    tipo_ok: TipoChavePix | None = None
    try:
        tipo_ok = TipoChavePix(tipo.strip().lower())
    except ValueError:
        validos = ", ".join(t.value for t in TipoChavePix)
        erros.append(("tipo", f"Tipo de chave deve ser um de: {validos}."))

    normalizada = ""
    if tipo_ok is not None:
        resultado = _NORMALIZADORES[tipo_ok](chave.strip())
        if resultado is None:
            erros.append(("chave", _MENSAGENS[tipo_ok]))
        else:
            normalizada = resultado

    nome = favorecido.strip()
    if not nome:
        erros.append(("favorecido", "Informe o nome do favorecido (quem recebe o Pix)."))
    elif len(nome) > _FAVORECIDO_MAX:
        erros.append(("favorecido", f"Favorecido deve ter no máximo {_FAVORECIDO_MAX} caracteres."))

    if erros or tipo_ok is None:
        raise ChavePixInvalida(erros)
    return ChavePix(tipo_ok, normalizada, nome)


# --- normalizadores: devolvem a chave normalizada ou None quando invalida -------------------


def _so_digitos(texto: str) -> str:
    return re.sub(r"\D", "", texto)


def _cpf(texto: str) -> str | None:
    if not re.fullmatch(r"[\d.\-\s]+", texto):
        return None
    digitos = _so_digitos(texto)
    if len(digitos) != 11 or len(set(digitos)) == 1:
        return None
    valores = [int(c) for c in digitos]
    for posicao in (9, 10):
        soma = sum(v * (posicao + 1 - i) for i, v in enumerate(valores[:posicao]))
        if (soma * 10 % 11) % 10 != valores[posicao]:
            return None
    return digitos


def _cnpj(texto: str) -> str | None:
    limpo = re.sub(r"[.\-/\s]", "", texto).upper()
    if not _CNPJ.fullmatch(limpo) or len(set(limpo)) == 1:
        return None
    valores = [ord(c) - ord("0") for c in limpo]  # alfanumerico: A=17, B=18...
    for posicao in (12, 13):
        pesos = _PESOS_CNPJ[len(_PESOS_CNPJ) - posicao :]
        resto = sum(v * p for v, p in zip(valores[:posicao], pesos, strict=True)) % 11
        if (0 if resto < 2 else 11 - resto) != valores[posicao]:
            return None
    return limpo


def _email(texto: str) -> str | None:
    if len(texto) > _EMAIL_MAX or not _EMAIL.fullmatch(texto):
        return None
    return texto.lower()


def _telefone(texto: str) -> str | None:
    if not re.fullmatch(r"[\d+()\-.\s]+", texto):
        return None
    digitos = _so_digitos(texto)
    if texto.startswith("+") and not digitos.startswith("55"):
        return None
    if len(digitos) in (12, 13) and digitos.startswith("55"):
        digitos = digitos[2:]
    if len(digitos) not in (10, 11):
        return None
    ddd, numero = digitos[:2], digitos[2:]
    if ddd[0] == "0" or ddd[1] == "0":
        return None
    celular = len(numero) == 9 and numero[0] == "9"
    fixo = len(numero) == 8 and numero[0] in "2345"
    return f"+55{ddd}{numero}" if celular or fixo else None


def _aleatoria(texto: str) -> str | None:
    return texto.lower() if _ALEATORIA.fullmatch(texto) else None


_NORMALIZADORES: Final = {
    TipoChavePix.CPF: _cpf,
    TipoChavePix.CNPJ: _cnpj,
    TipoChavePix.EMAIL: _email,
    TipoChavePix.TELEFONE: _telefone,
    TipoChavePix.ALEATORIA: _aleatoria,
}

_MENSAGENS: Final = {
    TipoChavePix.CPF: "CPF inválido: informe 11 dígitos com dígito verificador correto.",
    TipoChavePix.CNPJ: "CNPJ inválido: informe os 14 caracteres com dígito verificador correto.",
    TipoChavePix.EMAIL: "E-mail inválido (ex.: pix@loja.com.br, até 77 caracteres).",
    TipoChavePix.TELEFONE: "Telefone inválido: informe DDD e número, ex.: (11) 91234-5678.",
    TipoChavePix.ALEATORIA: "Chave aleatória inválida: deve ser um UUID (8-4-4-4-12 caracteres).",
}
