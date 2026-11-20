"""Regras de preco da loja demo."""

from decimal import Decimal

from app.application.config.entradas import EntradaPreco

PRECO = EntradaPreco(
    max_parcelas=18,
    repassa_taxa=True,
    desconto_pix_tipo="nenhum",  # preço à vista já é o Pix
    desconto_pix_valor=None,
    aceita_entrada_mais_cartao=True,
    desconto_teto=Decimal(100),
    desconto_degrau=Decimal(50),
    oportunidade_ativa=True,
    oportunidade_dias_minimos=14,
    oportunidade_valor=Decimal(100),
    oportunidade_conta_no_teto=False,  # por fora do teto
)
