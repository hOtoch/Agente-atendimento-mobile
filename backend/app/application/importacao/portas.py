"""Portas da importacao de planilhas: leitura do arquivo e geracao dos modelos."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from app.application.config.entradas import (
    EntradaLinhaEstoque,
    EntradaLinhaTroca,
    EntradaPreco,
    EntradaTaxa,
)
from app.application.config.modelos import ErroCampo

LINHA = "_linha"
"""Chave de `origens` com a celula inicial da linha (usada quando o campo nao tem celula)."""


@dataclass(frozen=True, slots=True)
class Leitura[T]:
    entradas: list[T]
    origens: list[dict[str, str]]
    erros: list[ErroCampo]


@dataclass(frozen=True, slots=True)
class LeituraPreco:
    entrada: EntradaPreco | None
    origens: dict[str, str]
    erros: list[ErroCampo] = field(default_factory=list)


class LeitorPlanilha(Protocol):
    """Le o conteudo de uma planilha e devolve entradas, celulas de origem e erros de leitura."""

    def ler_troca(self, conteudo: bytes) -> Leitura[EntradaLinhaTroca]: ...

    def ler_taxas(self, conteudo: bytes) -> tuple[Leitura[EntradaTaxa], LeituraPreco]: ...

    def ler_estoque(self, conteudo: bytes) -> Leitura[EntradaLinhaEstoque]: ...


class GeradorModelo(Protocol):
    def gerar(self, tipo: str) -> bytes:
        """Bytes da planilha modelo vazia. `KeyError` se o tipo nao existir."""
        ...
