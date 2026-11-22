"""EstadoAtendimento: imutabilidade, serializacao sem perda e fatos do kanban."""

from __future__ import annotations

import json
from dataclasses import FrozenInstanceError, replace
from datetime import date
from decimal import Decimal

import pytest

from app.application.agente.estado import EstadoAtendimento, fatos_do_lead
from app.domain.desconto import EstadoDesconto
from app.domain.ficha import Ficha, TipoPagamento
from app.domain.kanban import FatosDoLead
from app.domain.valores import Capacidade, Dinheiro, ModeloAparelho


def _ficha_sem_troca() -> Ficha:
    return (
        Ficha.vazia()
        .com_interesse(
            modelo=ModeloAparelho.de("iPhone 16"),
            capacidade=Capacidade(128),
            cor="Preto",
            sku_estoque_confirmado="SKU-1",
        )
        .com(tem_troca=False)
        .com_pagamento(tipo=TipoPagamento.PIX)
    )


def test_estado_vazio_e_imutavel() -> None:
    estado = EstadoAtendimento()
    assert estado.ficha == Ficha.vazia()
    assert estado.desconto == EstadoDesconto()
    assert not estado.estoque_consultado
    assert not estado.proposta_apresentada
    assert not estado.handoff_solicitado
    assert estado.motivo_handoff is None
    assert estado.ultima_proposta is None
    with pytest.raises(FrozenInstanceError):
        estado.estoque_consultado = True  # type: ignore[misc]


def test_ida_e_volta_do_estado_vazio() -> None:
    estado = EstadoAtendimento()
    assert EstadoAtendimento.de_dict(json.loads(json.dumps(estado.para_dict()))) == estado


def test_ida_e_volta_sem_perda_com_tudo_preenchido() -> None:
    estado = EstadoAtendimento(
        ficha=_ficha_sem_troca().com_usado(bateria_pct=79, outros_defeitos=("fone",)),
        desconto=EstadoDesconto(Dinheiro(Decimal("50.00"))),
        estoque_consultado=True,
        proposta_apresentada=True,
        handoff_solicitado=True,
        motivo_handoff="cliente quer fechar",
        ultima_proposta={"preco": "R$ 4.830,00", "alternativas": [{"parcelas": 12}]},
    )
    # passa por JSON de verdade, como no JSONB
    volta = EstadoAtendimento.de_dict(json.loads(json.dumps(estado.para_dict())))
    assert volta == estado


def test_de_dict_tolera_chaves_ausentes() -> None:
    assert EstadoAtendimento.de_dict({}) == EstadoAtendimento()


def test_fatos_do_lead_vazio() -> None:
    assert fatos_do_lead(EstadoAtendimento()) == FatosDoLead()


def test_aparelho_definido_exige_modelo_e_capacidade() -> None:
    so_modelo = Ficha.vazia().com_interesse(modelo=ModeloAparelho.de("iPhone 16"))
    assert not fatos_do_lead(EstadoAtendimento(ficha=so_modelo)).aparelho_definido
    completo = so_modelo.com_interesse(capacidade=Capacidade(128))
    assert fatos_do_lead(EstadoAtendimento(ficha=completo)).aparelho_definido


def test_qualificado_vem_da_trava_de_preco() -> None:
    ficha = _ficha_sem_troca().com(data_prevista_compra=date(2026, 12, 1))
    fatos = fatos_do_lead(EstadoAtendimento(ficha=ficha, estoque_consultado=True))
    assert fatos.qualificado
    assert fatos.estoque_consultado
    assert not fatos.handoff_realizado
    assert not fatos_do_lead(EstadoAtendimento(ficha=_ficha_sem_troca())).qualificado


def test_handoff_solicitado_vira_handoff_realizado() -> None:
    estado = replace(EstadoAtendimento(), handoff_solicitado=True)
    assert fatos_do_lead(estado).handoff_realizado


def test_acordo_comeca_vazio_e_faz_ida_e_volta() -> None:
    assert EstadoAtendimento().acordo is None
    acordo = {"fechado_em": "2026-11-20T15:00:00+00:00", "aparelho": {"sku": "X"}, "pagamento": {}}
    estado = replace(EstadoAtendimento(), acordo=acordo)
    volta = EstadoAtendimento.de_dict(json.loads(json.dumps(estado.para_dict())))
    assert volta.acordo == acordo
    assert volta == estado
