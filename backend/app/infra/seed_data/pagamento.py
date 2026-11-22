"""Formas de pagamento e chave Pix da loja demo (a chave e fictícia: domínio `.exemplo`)."""

from app.application.config.entradas import EntradaPagamento

PAGAMENTO = EntradaPagamento(
    aceita_pix=True,
    aceita_debito=True,
    aceita_credito=True,
    chave_pix_tipo="email",
    chave_pix="pix@lojademo.exemplo",
    chave_pix_favorecido="Loja Demo Celulares",
)
