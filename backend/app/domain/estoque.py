"""Item de estoque e filtro puro de busca (sem IO)."""

from __future__ import annotations

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
