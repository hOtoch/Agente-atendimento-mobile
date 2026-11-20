import json
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel

ARQUIVO_PRODUTOS = Path(__file__).parent / "dados" / "produtos.json"


class Produto(BaseModel):
    sku: str
    descricao: str
    preco: str  # decimal como string, ex. "5999.00"
    estoque: int
    atualizado_em: datetime


class PaginaProdutos(BaseModel):
    itens: list[Produto]
    pagina: int
    tamanho: int
    total: int
    total_paginas: int


def carregar_produtos(caminho: Path = ARQUIVO_PRODUTOS) -> list[Produto]:
    bruto = json.loads(caminho.read_text(encoding="utf-8"))
    return [Produto.model_validate(item) for item in bruto]


def paginar(produtos: list[Produto], pagina: int, tamanho: int) -> PaginaProdutos:
    total = len(produtos)
    inicio = (pagina - 1) * tamanho
    return PaginaProdutos(
        itens=produtos[inicio : inicio + tamanho],
        pagina=pagina,
        tamanho=tamanho,
        total=total,
        total_paginas=-(-total // tamanho),
    )
