"""Estoque local da loja demo: precos Pix em R$, sempre acima do valor de troca do modelo."""

from decimal import Decimal

from app.application.config.entradas import EntradaLinhaEstoque

# (modelo, GB, cor, condicao, preco Pix, quantidade, bateria %)
_ITENS: tuple[tuple[str, int, str, str, int, int, int | None], ...] = (
    ("iPhone 11", 64, "Preto", "seminovo", 1399, 3, 86),
    ("iPhone 12", 128, "Branco", "seminovo", 1999, 2, 85),
    ("iPhone 13", 128, "Azul", "seminovo", 2399, 2, 88),
    ("iPhone 13", 128, "Preto", "seminovo", 2499, 1, 92),
    ("iPhone 13", 256, "Estelar", "seminovo", 2799, 0, 86),
    ("iPhone 14", 128, "Meia-noite", "seminovo", 2999, 2, 90),
    ("iPhone 14", 256, "Roxo", "seminovo", 3399, 1, 94),
    ("iPhone 14 Pro", 128, "Roxo-profundo", "seminovo", 4399, 1, 87),
    ("iPhone 14 Pro Max", 256, "Preto-espacial", "seminovo", 5599, 0, 91),
    ("iPhone 15", 128, "Rosa", "novo", 4199, 3, None),
    ("iPhone 15", 128, "Preto", "novo", 4199, 4, None),
    ("iPhone 15", 256, "Azul", "novo", 4699, 2, None),
    ("iPhone 15 Plus", 128, "Verde", "novo", 4799, 1, None),
    ("iPhone 15 Pro", 256, "Titânio Natural", "seminovo", 5899, 1, 95),
    ("iPhone 15 Pro Max", 256, "Titânio Azul", "seminovo", 6499, 1, 89),
    ("iPhone 16e", 128, "Preto", "novo", 3799, 2, None),
    ("iPhone 16", 128, "Preto", "novo", 4830, 5, None),
    ("iPhone 16", 128, "Ultramarino", "novo", 4830, 3, None),
    ("iPhone 16", 256, "Branco", "novo", 5430, 2, None),
    ("iPhone 16", 512, "Preto", "novo", 6290, 0, None),
    ("iPhone 16 Plus", 128, "Rosa", "novo", 5499, 2, None),
    ("iPhone 16 Pro", 128, "Titânio Deserto", "novo", 7499, 2, None),
    ("iPhone 16 Pro", 256, "Titânio Natural", "novo", 8199, 1, None),
    ("iPhone 16 Pro", 256, "Titânio Branco", "seminovo", 6799, 1, 97),
    ("iPhone 16 Pro Max", 256, "Titânio Preto", "novo", 8999, 1, None),
    ("iPhone 17", 256, "Lavanda", "novo", 6299, 3, None),
    ("iPhone 17 Pro", 256, "Laranja Cósmico", "novo", 9299, 1, None),
    ("iPhone 17 Pro Max", 512, "Azul Profundo", "novo", 11299, 0, None),
)


def _sku(modelo: str, gb: int, cor: str, condicao: str, seq: int) -> str:
    base = modelo.replace("iPhone ", "IP").replace(" ", "").upper()
    cor_curta = "".join(c for c in cor.upper() if c.isascii() and c.isalnum())[:4]
    return f"DEMO-{base}-{gb}-{cor_curta}-{condicao[:2].upper()}{seq:02d}"


ESTOQUE: tuple[EntradaLinhaEstoque, ...] = tuple(
    EntradaLinhaEstoque(
        sku=_sku(modelo, gb, cor, condicao, i),
        marca="Apple",
        modelo=modelo,
        capacidade_gb=gb,
        cor=cor,
        condicao=condicao,
        preco_pix=Decimal(preco),
        quantidade=qtd,
        bateria_pct=bateria,
    )
    for i, (modelo, gb, cor, condicao, preco, qtd, bateria) in enumerate(_ITENS, start=1)
)
