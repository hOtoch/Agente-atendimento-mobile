"""Item de estoque, filtro puro de busca e resolucao do modelo pedido (sem IO)."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

from app.domain.valores import Capacidade, Dinheiro, ModeloAparelho


class Condicao(StrEnum):
    NOVO = "novo"
    SEMINOVO = "seminovo"


@dataclass(frozen=True, slots=True)
class ItemEstoque:
    """Unidade vendavel do estoque de uma loja.

    `bateria_pct` so existe para seminovo (0 a 100). `desatualizado` e marcado pelo
    decorator de resiliencia quando o dado veio de cache/fallback.
    """

    sku: str
    modelo: ModeloAparelho
    capacidade: Capacidade
    cor: str | None
    condicao: Condicao
    preco_pix: Dinheiro
    quantidade: int
    bateria_pct: int | None = None
    desatualizado: bool = False

    def __post_init__(self) -> None:
        if self.quantidade < 0:
            raise ValueError(f"quantidade nao pode ser negativa: {self.quantidade}")
        if self.bateria_pct is not None:
            if self.condicao is not Condicao.SEMINOVO:
                raise ValueError("bateria_pct so se aplica a seminovo")
            if not 0 <= self.bateria_pct <= 100:
                raise ValueError(f"bateria_pct fora de 0..100: {self.bateria_pct}")

    @property
    def disponivel(self) -> bool:
        return self.quantidade > 0


@dataclass(frozen=True, slots=True)
class MapeamentoSku:
    """Traducao de um SKU do ERP (da loja) para o modelo do dominio."""

    sku_externo: str
    modelo: ModeloAparelho
    capacidade: Capacidade
    cor: str | None
    condicao: Condicao


def _norm_cor(texto: str) -> str:
    sem_acento = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return " ".join(sem_acento.lower().split())


def filtrar(
    itens: Iterable[ItemEstoque],
    modelo: str | ModeloAparelho,
    capacidade: Capacidade | None = None,
    cor: str | None = None,
) -> list[ItemEstoque]:
    """Itens disponiveis do modelo (busca tolerante), opcionalmente por capacidade e cor.

    Texto de `modelo` e normalizado por `ModeloAparelho.de` (ValueError se vazio);
    `cor` ignora acento e caixa. Preserva a ordem de entrada.
    """
    alvo = modelo if isinstance(modelo, ModeloAparelho) else ModeloAparelho.de(modelo)
    cor_alvo = _norm_cor(cor) if cor is not None else None
    return [
        i
        for i in itens
        if i.disponivel
        and i.modelo == alvo
        and (capacidade is None or i.capacidade == capacidade)
        and (cor_alvo is None or (i.cor is not None and _norm_cor(i.cor) == cor_alvo))
    ]


@dataclass(frozen=True, slots=True)
class ModeloResolvido:
    modelo: ModeloAparelho


@dataclass(frozen=True, slots=True)
class ModeloAmbiguo:
    """O texto casa com mais de um modelo do estoque: o cliente precisa escolher."""

    candidatos: tuple[ModeloAparelho, ...]


@dataclass(frozen=True, slots=True)
class ModeloForaDoEstoque:
    """Nem iPhone conhecido nem modelo que a loja tenha no estoque."""


ResolucaoModelo = ModeloResolvido | ModeloAmbiguo | ModeloForaDoEstoque


def _chave_modelo(texto: str) -> str:
    """Forma comparavel: sem acento, caixa, espacos e separadores."""
    ascii_ = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]", "", ascii_)


def _chaves(modelo: ModeloAparelho) -> tuple[str, str]:
    return _chave_modelo(modelo.nome), _chave_modelo(f"{modelo.marca} {modelo.nome}")


def _casa(chave: str, alvo: str, exato: bool) -> bool:
    return chave == alvo if exato else chave.startswith(alvo)


def resolver_modelo(texto: str, modelos_do_estoque: Iterable[ModeloAparelho]) -> ResolucaoModelo:
    """Modelo que o cliente pediu -> modelo da loja.

    iPhone conhecido vale sempre (mesmo sem estoque). Fora isso, casa com os modelos do estoque,
    com ou sem a marca na frente: nome exato antes de comeco do nome. Mais de um candidato e
    ambiguo; nenhum e `ModeloForaDoEstoque`.
    """
    try:
        pedido = ModeloAparelho.de(texto)
    except ValueError:
        return ModeloForaDoEstoque()
    if pedido.conhecido:
        return ModeloResolvido(pedido)
    alvo = _chave_modelo(texto)
    if not alvo:
        return ModeloForaDoEstoque()
    modelos = list(dict.fromkeys(modelos_do_estoque))
    for exato in (True, False):
        candidatos = tuple(m for m in modelos if any(_casa(k, alvo, exato) for k in _chaves(m)))
        if len(candidatos) == 1:
            return ModeloResolvido(candidatos[0])
        if candidatos:
            return ModeloAmbiguo(candidatos)
    return ModeloForaDoEstoque()
