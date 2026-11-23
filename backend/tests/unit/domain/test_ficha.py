"""Testes da ficha de qualificacao e da trava de preco."""

from __future__ import annotations

import json
from dataclasses import fields
from datetime import date
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.domain.ficha import (
    Ficha,
    InteresseInformado,
    PagamentoInformado,
    Pendencia,
    TipoPagamento,
    UsadoInformado,
    pendencias,
    pode_passar_preco,
)
from app.domain.valores import Bandeira, Capacidade, Dinheiro, ModeloAparelho

P = Pendencia

INTERESSE_OK: dict[str, Any] = {
    "modelo": ModeloAparelho.de("iPhone 15 Pro"),
    "capacidade": Capacidade("256GB"),
    "sku_estoque_confirmado": "SKU-15PRO-256",
}
USADO_OK: dict[str, Any] = {
    "modelo": ModeloAparelho.de("iPhone 12"),
    "capacidade": Capacidade("128GB"),
    "tela_danificada": False,
    "traseira_danificada": False,
    "carcaca_marcada": True,
    "bateria_pct": 84,
    "camera_ok": True,
    "outros_defeitos": (),
    "peca_trocada": False,
}
PAGAMENTO_POR_TIPO: dict[TipoPagamento, dict[str, Any]] = {
    TipoPagamento.PIX: {},
    TipoPagamento.DEBITO: {"bandeira": Bandeira.VISA},
    TipoPagamento.CREDITO: {"parcelas": 10, "bandeira": Bandeira.MASTERCARD},
    TipoPagamento.ENTRADA_MAIS_CREDITO: {
        "entrada": Dinheiro.de("1500"),
        "parcelas": 6,
        "bandeira": Bandeira.ELO,
    },
}
DATA = date(2026, 12, 20)


def ficha_completa(com_troca: bool = True, tipo: TipoPagamento = TipoPagamento.PIX) -> Ficha:
    ficha = (
        Ficha.vazia()
        .com_interesse(**INTERESSE_OK)
        .com(tem_troca=com_troca, data_prevista_compra=DATA)
        .com_pagamento(tipo=tipo, **PAGAMENTO_POR_TIPO[tipo])
    )
    return ficha.com_usado(**USADO_OK) if com_troca else ficha


# --- vazia / sem troca / completa ------------------------------------------------


def test_ficha_vazia_lista_so_o_que_e_aplicavel_e_bloqueia_preco() -> None:
    ficha = Ficha.vazia()
    assert pendencias(ficha) == [
        P.APARELHO_MODELO,
        P.APARELHO_CAPACIDADE,
        P.ESTOQUE_CONFIRMADO,
        P.TEM_TROCA,
        P.DATA_COMPRA,
        P.PAGAMENTO_TIPO,
    ]
    assert pode_passar_preco(ficha) is False


def test_sem_troca_dispensa_todo_o_bloco_do_usado() -> None:
    ficha = Ficha.vazia().com(tem_troca=False)
    restantes = pendencias(ficha)
    assert P.TEM_TROCA not in restantes
    assert not [p for p in restantes if p.name.startswith("USADO_")]


def test_com_troca_exige_todo_o_bloco_do_usado_em_ordem() -> None:
    restantes = pendencias(Ficha.vazia().com(tem_troca=True))
    assert restantes == [
        P.APARELHO_MODELO,
        P.APARELHO_CAPACIDADE,
        P.ESTOQUE_CONFIRMADO,
        P.USADO_MODELO,
        P.USADO_CAPACIDADE,
        P.USADO_TELA,
        P.USADO_TRASEIRA,
        P.USADO_CARCACA,
        P.USADO_BATERIA,
        P.DATA_COMPRA,
        P.PAGAMENTO_TIPO,
    ]


def test_usado_sem_bateria_gera_pendencia_de_bateria() -> None:
    ficha = ficha_completa(True).com_usado(bateria_pct=None)
    assert pendencias(ficha) == [P.USADO_BATERIA]
    assert pode_passar_preco(ficha) is False


@pytest.mark.parametrize("com_troca", [True, False])
@pytest.mark.parametrize("tipo", list(TipoPagamento))
def test_ficha_completa_libera_preco(com_troca: bool, tipo: TipoPagamento) -> None:
    ficha = ficha_completa(com_troca, tipo)
    assert pendencias(ficha) == []
    assert pode_passar_preco(ficha) is True


def test_sem_troca_ignora_dados_de_usado_ja_informados() -> None:
    ficha = ficha_completa(True).com(tem_troca=False)
    assert pode_passar_preco(ficha) is True


# --- cada campo faltante ----------------------------------------------------------

CAMPOS_FALTANTES = [
    ("com_interesse", "modelo", P.APARELHO_MODELO),
    ("com_interesse", "capacidade", P.APARELHO_CAPACIDADE),
    ("com_interesse", "sku_estoque_confirmado", P.ESTOQUE_CONFIRMADO),
    ("com", "tem_troca", P.TEM_TROCA),
    ("com_usado", "modelo", P.USADO_MODELO),
    ("com_usado", "capacidade", P.USADO_CAPACIDADE),
    ("com_usado", "tela_danificada", P.USADO_TELA),
    ("com_usado", "traseira_danificada", P.USADO_TRASEIRA),
    ("com_usado", "carcaca_marcada", P.USADO_CARCACA),
    ("com_usado", "bateria_pct", P.USADO_BATERIA),
    ("com", "data_prevista_compra", P.DATA_COMPRA),
    ("com_pagamento", "tipo", P.PAGAMENTO_TIPO),
]


@pytest.mark.parametrize(("metodo", "campo", "esperada"), CAMPOS_FALTANTES)
def test_cada_campo_faltante_gera_a_pendencia_certa(
    metodo: str, campo: str, esperada: Pendencia
) -> None:
    base = ficha_completa(True, TipoPagamento.CREDITO)
    if campo == "tem_troca":
        # None = ainda nao perguntado: o bloco do usado some e a pergunta volta.
        ficha = base.com(tem_troca=None)
        assert pendencias(ficha) == [P.TEM_TROCA]
        return
    ficha = getattr(base, metodo)(**{campo: None})
    assert pendencias(ficha) == [esperada]
    assert pode_passar_preco(ficha) is False


def test_cor_nao_e_obrigatoria() -> None:
    ficha = ficha_completa()
    assert ficha.interesse.cor is None
    assert pode_passar_preco(ficha) is True
    assert ficha.com_interesse(cor="Titânio Azul").interesse.cor == "Titânio Azul"


def test_avaliacao_do_usado_so_pergunta_tela_traseira_carcaca_e_bateria() -> None:
    """Camera, outros defeitos e peca trocada nao sao perguntados (so valem se o cliente contar)."""
    ficha = ficha_completa().com_usado(camera_ok=None, outros_defeitos=None, peca_trocada=None)
    assert pendencias(ficha) == []


def test_usado_avaliado_na_loja_dispensa_as_perguntas_de_estado() -> None:
    """Modelo sem valor na tabela da loja: nao adianta perguntar o estado do aparelho."""
    ficha = (
        ficha_completa()
        .com(tem_troca=True)
        .com_usado(
            capacidade=None,
            tela_danificada=None,
            traseira_danificada=None,
            carcaca_marcada=None,
            bateria_pct=None,
            avaliacao_na_loja=True,
        )
    )
    assert pendencias(ficha) == []
    assert pendencias(ficha.com_usado(modelo=None))[0] is P.USADO_MODELO
    assert Ficha.de_dict(json.loads(json.dumps(ficha.para_dict()))) == ficha
    assert Ficha.de_dict({"usado": {}}).usado.avaliacao_na_loja is False


def test_bateria_zero_conta_como_informada() -> None:
    assert P.USADO_BATERIA not in pendencias(ficha_completa().com_usado(bateria_pct=0))


# --- pagamento por tipo -----------------------------------------------------------

BASE_PAGAMENTO = ficha_completa(False).com_pagamento(tipo=None)


@pytest.mark.parametrize(
    ("tipo", "esperadas"),
    [
        (TipoPagamento.PIX, []),
        (TipoPagamento.DEBITO, [P.PAGAMENTO_BANDEIRA]),
        (TipoPagamento.CREDITO, [P.PAGAMENTO_PARCELAS, P.PAGAMENTO_BANDEIRA]),
        (
            TipoPagamento.ENTRADA_MAIS_CREDITO,
            [P.PAGAMENTO_PARCELAS, P.PAGAMENTO_BANDEIRA, P.PAGAMENTO_ENTRADA],
        ),
    ],
)
def test_pagamento_exige_os_campos_certos_por_tipo(
    tipo: TipoPagamento, esperadas: list[Pendencia]
) -> None:
    assert pendencias(BASE_PAGAMENTO.com_pagamento(tipo=tipo)) == esperadas


@pytest.mark.parametrize("tipo", list(TipoPagamento))
def test_pagamento_com_campos_do_tipo_nao_tem_pendencia(tipo: TipoPagamento) -> None:
    ficha = BASE_PAGAMENTO.com_pagamento(tipo=tipo, **PAGAMENTO_POR_TIPO[tipo])
    assert pendencias(ficha) == []


def test_entrada_zero_conta_como_informada() -> None:
    ficha = BASE_PAGAMENTO.com_pagamento(
        tipo=TipoPagamento.ENTRADA_MAIS_CREDITO,
        entrada=Dinheiro.zero(),
        parcelas=3,
        bandeira=Bandeira.VISA,
    )
    assert pendencias(ficha) == []


# --- atualizacao parcial ----------------------------------------------------------


def test_atualizacao_parcial_preserva_campos_e_nao_muta_o_original() -> None:
    original = Ficha.vazia().com_interesse(modelo=ModeloAparelho.de("iPhone 14"))
    nova = original.com_interesse(capacidade=Capacidade(128)).com(tem_troca=True)
    nova = nova.com_usado(bateria_pct=80).com_usado(tela_danificada=True)
    nova = nova.com_pagamento(tipo=TipoPagamento.CREDITO).com_pagamento(parcelas=12)
    assert nova.interesse.modelo == ModeloAparelho.de("iPhone 14")
    assert nova.interesse.capacidade == 128
    assert nova.tem_troca is True
    assert nova.usado.bateria_pct == 80
    assert nova.usado.tela_danificada is True
    assert nova.pagamento.tipo is TipoPagamento.CREDITO
    assert nova.pagamento.parcelas == 12
    assert original.interesse.capacidade is None
    assert original.tem_troca is None


def test_atualizacao_pode_apagar_com_none_explicito() -> None:
    ficha = ficha_completa().com_usado(bateria_pct=None)
    assert ficha.usado.bateria_pct is None
    assert ficha.usado.tela_danificada is False


@pytest.mark.parametrize(
    "chamada",
    [
        lambda f: f.com_interesse(foo=1),
        lambda f: f.com_usado(foo=1),
        lambda f: f.com_pagamento(foo=1),
        lambda f: f.com(foo=1),
        lambda f: f.com(interesse=InteresseInformado()),
    ],
)
def test_campo_desconhecido_levanta_erro(chamada: Any) -> None:
    with pytest.raises(TypeError):
        chamada(Ficha.vazia())


def test_ficha_e_imutavel() -> None:
    ficha = Ficha.vazia()
    with pytest.raises(AttributeError):
        ficha.tem_troca = True  # type: ignore[misc]
    with pytest.raises(AttributeError):
        ficha.interesse.cor = "x"  # type: ignore[misc]


# --- serializacao -----------------------------------------------------------------


def test_dict_da_ficha_vazia_ida_e_volta() -> None:
    ficha = Ficha.vazia()
    assert Ficha.de_dict(ficha.para_dict()) == ficha


@pytest.mark.parametrize("com_troca", [True, False])
@pytest.mark.parametrize("tipo", list(TipoPagamento))
def test_dict_da_ficha_completa_ida_e_volta_via_json(com_troca: bool, tipo: TipoPagamento) -> None:
    ficha = ficha_completa(com_troca, tipo)
    carregada = json.loads(json.dumps(ficha.para_dict()))
    assert Ficha.de_dict(carregada) == ficha


def test_dict_e_json_friendly() -> None:
    d = ficha_completa(True, TipoPagamento.ENTRADA_MAIS_CREDITO).para_dict()
    assert d["data_prevista_compra"] == "2026-12-20"
    assert d["pagamento"]["entrada"] == "1500.00"
    assert d["pagamento"]["tipo"] == "entrada_mais_credito"
    assert d["pagamento"]["bandeira"] == "elo"
    assert d["interesse"]["modelo"]["nome"] == "iPhone 15 Pro"
    assert d["interesse"]["modelo"]["marca"] == "Apple"
    assert d["interesse"]["capacidade"] == 256
    assert d["usado"]["outros_defeitos"] == []
    json.dumps(d)


def test_dict_preserva_distincao_entre_none_e_vazio() -> None:
    sem_perguntar = Ficha.de_dict(Ficha.vazia().para_dict())
    assert sem_perguntar.usado.outros_defeitos is None
    nenhum = Ficha.de_dict(Ficha.vazia().com_usado(outros_defeitos=()).para_dict())
    assert nenhum.usado.outros_defeitos == ()


def test_de_dict_aceita_dict_incompleto_como_ficha_parcial() -> None:
    assert Ficha.de_dict({}) == Ficha.vazia()
    assert Ficha.de_dict({"tem_troca": False}) == Ficha.vazia().com(tem_troca=False)


# --- propriedades -----------------------------------------------------------------

_modelos = st.sampled_from(["iPhone 11", "iPhone 13 Pro", "Galaxy S21"]).map(ModeloAparelho.de)


def _opcional(valores: st.SearchStrategy[Any]) -> st.SearchStrategy[Any]:
    return st.one_of(st.none(), valores)


_interesses = st.builds(
    InteresseInformado,
    modelo=_opcional(_modelos),
    capacidade=_opcional(st.sampled_from([64, 128, 256, 1024]).map(Capacidade)),
    cor=_opcional(st.text(max_size=8)),
    sku_estoque_confirmado=_opcional(st.text(min_size=1, max_size=8)),
)
_usados = st.builds(
    UsadoInformado,
    modelo=_opcional(_modelos),
    capacidade=_opcional(st.sampled_from([64, 128, 256]).map(Capacidade)),
    tela_danificada=_opcional(st.booleans()),
    traseira_danificada=_opcional(st.booleans()),
    carcaca_marcada=_opcional(st.booleans()),
    bateria_pct=_opcional(st.integers(0, 100)),
    camera_ok=_opcional(st.booleans()),
    outros_defeitos=_opcional(st.lists(st.text(min_size=1, max_size=5), max_size=2).map(tuple)),
    peca_trocada=_opcional(st.booleans()),
)
_pagamentos = st.builds(
    PagamentoInformado,
    tipo=_opcional(st.sampled_from(list(TipoPagamento))),
    parcelas=_opcional(st.integers(1, 18)),
    bandeira=_opcional(st.sampled_from(list(Bandeira))),
    entrada=_opcional(st.integers(0, 5000).map(Dinheiro.de)),
)
_fichas = st.builds(
    Ficha,
    interesse=_interesses,
    tem_troca=_opcional(st.booleans()),
    usado=_usados,
    data_prevista_compra=_opcional(st.dates()),
    pagamento=_pagamentos,
)


def _preenchidos(obj: object) -> dict[str, Any]:
    return {f.name: getattr(obj, f.name) for f in fields(obj) if getattr(obj, f.name) is not None}  # type: ignore[arg-type]


@given(ficha=_fichas, extra=_fichas)
def test_preencher_campos_nunca_adiciona_pendencias(ficha: Ficha, extra: Ficha) -> None:
    """Mantidos tem_troca e tipo de pagamento, preencher campos so remove pendencias."""
    preenchida = (
        ficha.com_interesse(**_preenchidos(extra.interesse))
        .com_usado(**_preenchidos(extra.usado))
        .com_pagamento(**{k: v for k, v in _preenchidos(extra.pagamento).items() if k != "tipo"})
    )
    if extra.data_prevista_compra is not None:
        preenchida = preenchida.com(data_prevista_compra=extra.data_prevista_compra)
    assert set(pendencias(preenchida)) <= set(pendencias(ficha))


@given(ficha=_fichas)
def test_pendencias_vem_em_ordem_sem_repeticao_e_preco_segue_a_trava(ficha: Ficha) -> None:
    lista = pendencias(ficha)
    assert lista == sorted(set(lista), key=list(Pendencia).index)
    assert pode_passar_preco(ficha) is (lista == [])


@given(ficha=_fichas)
def test_ida_e_volta_do_dict_sem_perda(ficha: Ficha) -> None:
    assert Ficha.de_dict(json.loads(json.dumps(ficha.para_dict()))) == ficha
