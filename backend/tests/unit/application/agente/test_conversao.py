"""Contrato da conversao ficha -> entradas de calculo (hypothesis)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.application.agente.conversao import (
    FichaIncompleta,
    entradas_de_calculo,
)
from app.domain.ficha import (
    Ficha,
    InteresseInformado,
    PagamentoInformado,
    TipoPagamento,
    UsadoInformado,
    pendencias,
)
from app.domain.pagamento import Credito, Debito, EntradaMaisCredito, PixDinheiro
from app.domain.troca import CondicaoUsado
from app.domain.valores import MODELOS_IPHONE, Bandeira, Capacidade, Dinheiro, ModeloAparelho

_modelos = st.sampled_from(MODELOS_IPHONE).map(ModeloAparelho.de)
_capacidades = st.sampled_from([64, 128, 256, 512, 1024]).map(Capacidade)
_bool = st.booleans()


@st.composite
def usados(draw: st.DrawFn) -> UsadoInformado:
    return UsadoInformado(
        modelo=draw(_modelos),
        capacidade=draw(_capacidades),
        tela_danificada=draw(_bool),
        traseira_danificada=draw(_bool),
        carcaca_marcada=draw(_bool),
        bateria_pct=draw(st.integers(0, 100)),
        camera_ok=draw(_bool),
        outros_defeitos=tuple(draw(st.lists(st.text(min_size=1, max_size=10), max_size=3))),
        peca_trocada=draw(_bool),
    )


@st.composite
def pagamentos(draw: st.DrawFn) -> PagamentoInformado:
    tipo = draw(st.sampled_from(list(TipoPagamento)))
    bandeira = draw(st.sampled_from(list(Bandeira)))
    parcelas = draw(st.integers(1, 21))
    entrada = Dinheiro(Decimal(draw(st.integers(0, 5000))))
    if tipo is TipoPagamento.PIX:
        return PagamentoInformado(tipo=tipo)
    if tipo is TipoPagamento.DEBITO:
        return PagamentoInformado(tipo=tipo, bandeira=bandeira)
    if tipo is TipoPagamento.CREDITO:
        return PagamentoInformado(tipo=tipo, parcelas=parcelas, bandeira=bandeira)
    return PagamentoInformado(tipo=tipo, parcelas=parcelas, bandeira=bandeira, entrada=entrada)


@st.composite
def fichas_completas(draw: st.DrawFn) -> Ficha:
    tem_troca = draw(_bool)
    return Ficha(
        interesse=InteresseInformado(
            modelo=draw(_modelos),
            capacidade=draw(_capacidades),
            cor=draw(st.none() | st.text(min_size=1, max_size=8)),
            sku_estoque_confirmado=draw(st.text(min_size=1, max_size=12)),
        ),
        tem_troca=tem_troca,
        usado=draw(usados()) if tem_troca else UsadoInformado(),
        data_prevista_compra=draw(st.dates(date(2026, 1, 1), date(2030, 1, 1))),
        pagamento=draw(pagamentos()),
    )


@settings(max_examples=200)
@given(fichas_completas())
def test_toda_ficha_sem_pendencias_converte_sem_erro(ficha: Ficha) -> None:
    assert pendencias(ficha) == []  # a estrategia gera fichas validas
    entradas = entradas_de_calculo(ficha)

    assert entradas.sku == ficha.interesse.sku_estoque_confirmado
    assert entradas.data_compra == ficha.data_prevista_compra
    if ficha.tem_troca:
        assert entradas.usado is not None
        assert isinstance(entradas.usado.condicao, CondicaoUsado)
        assert entradas.usado.modelo == ficha.usado.modelo
        assert entradas.usado.capacidade == ficha.usado.capacidade
    else:
        assert entradas.usado is None
    tipo = ficha.pagamento.tipo
    esperado = {
        TipoPagamento.PIX: PixDinheiro,
        TipoPagamento.DEBITO: Debito,
        TipoPagamento.CREDITO: Credito,
        TipoPagamento.ENTRADA_MAIS_CREDITO: EntradaMaisCredito,
    }[tipo]  # type: ignore[index]
    assert isinstance(entradas.forma, esperado)


def test_ficha_vazia_nao_converte() -> None:
    with pytest.raises(FichaIncompleta):
        entradas_de_calculo(Ficha.vazia())


@settings(max_examples=100)
@given(fichas_completas(), st.sampled_from(["data", "tipo", "sku"]))
def test_ficha_com_pendencia_nao_converte(ficha: Ficha, apagar: str) -> None:
    if apagar == "data":
        ficha = ficha.com(data_prevista_compra=None)
    elif apagar == "tipo":
        ficha = ficha.com_pagamento(tipo=None)
    else:
        ficha = ficha.com_interesse(sku_estoque_confirmado=None)
    assert pendencias(ficha)
    with pytest.raises(FichaIncompleta):
        entradas_de_calculo(ficha)
