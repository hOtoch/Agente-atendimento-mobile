"""Formas de pagamento que a loja aceita (o dominio decide, nao o prompt)."""

from __future__ import annotations

import pytest

from app.domain.ficha import TipoPagamento
from app.domain.formas_pagamento import FormasAceitas


def test_todas_as_formas_ligadas() -> None:
    formas = FormasAceitas.de(pix=True, debito=True, credito=True, entrada_mais_cartao=True)
    assert formas.tipos() == (
        TipoPagamento.PIX,
        TipoPagamento.DEBITO,
        TipoPagamento.CREDITO,
        TipoPagamento.ENTRADA_MAIS_CREDITO,
    )
    for tipo in TipoPagamento:
        assert formas.aceita(tipo)


def test_forma_desligada_nao_e_aceita() -> None:
    formas = FormasAceitas.de(pix=True, debito=False, credito=True, entrada_mais_cartao=False)
    assert formas.aceita(TipoPagamento.PIX)
    assert not formas.aceita(TipoPagamento.DEBITO)
    assert formas.aceita(TipoPagamento.CREDITO)
    assert not formas.aceita(TipoPagamento.ENTRADA_MAIS_CREDITO)
    assert formas.tipos() == (TipoPagamento.PIX, TipoPagamento.CREDITO)


def test_entrada_mais_cartao_exige_credito() -> None:
    formas = FormasAceitas.de(pix=True, debito=True, credito=False, entrada_mais_cartao=True)
    assert not formas.aceita(TipoPagamento.ENTRADA_MAIS_CREDITO)


def test_nenhuma_forma() -> None:
    formas = FormasAceitas.de(pix=False, debito=False, credito=False, entrada_mais_cartao=False)
    assert formas.tipos() == ()


def test_padrao_aceita_pix_debito_e_credito_sem_entrada() -> None:
    formas = FormasAceitas()
    assert formas.tipos() == (TipoPagamento.PIX, TipoPagamento.DEBITO, TipoPagamento.CREDITO)


@pytest.mark.parametrize("tipo", list(TipoPagamento))
def test_aceita_cobre_todos_os_tipos(tipo: TipoPagamento) -> None:
    assert isinstance(FormasAceitas().aceita(tipo), bool)
