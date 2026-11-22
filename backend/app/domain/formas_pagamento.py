"""Formas de pagamento que a loja aceita: o dominio diz se um `TipoPagamento` vale.

Pix, debito e credito sao ligados/desligados pela loja; entrada + cartao vem das regras de preco
(`RegrasPreco.aceita_entrada_mais_cartao`, fonte unica) e exige o credito ligado. Dominio puro.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Self

from app.domain.ficha import TipoPagamento


@dataclass(frozen=True, slots=True)
class FormasAceitas:
    pix: bool = True
    debito: bool = True
    credito: bool = True
    entrada_mais_credito: bool = False

    @classmethod
    def de(cls, *, pix: bool, debito: bool, credito: bool, entrada_mais_cartao: bool) -> Self:
        """Entrada + cartao parcela no credito: sem credito ligado, nao ha entrada + cartao."""
        return cls(pix, debito, credito, entrada_mais_cartao and credito)

    def aceita(self, tipo: TipoPagamento) -> bool:
        match tipo:
            case TipoPagamento.PIX:
                return self.pix
            case TipoPagamento.DEBITO:
                return self.debito
            case TipoPagamento.CREDITO:
                return self.credito
            case TipoPagamento.ENTRADA_MAIS_CREDITO:
                return self.entrada_mais_credito

    def tipos(self) -> tuple[TipoPagamento, ...]:
        """As formas aceitas, na ordem de apresentacao (Pix, debito, credito, entrada + cartao)."""
        return tuple(t for t in TipoPagamento if self.aceita(t))
