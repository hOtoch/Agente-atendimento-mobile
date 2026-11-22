"""Regra de negocio: quando um item vindo do ERP pode ser ofertado pelo agente."""

from decimal import Decimal
from typing import Any

import pytest

from app.domain.estoque import Condicao
from app.domain.oferta import MotivoDescarte, motivo_nao_ofertavel
from app.domain.valores import Capacidade, Dinheiro


def _valido(**mudancas: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "e_celular": True,
        "disponivel": True,
        "quantidade": 1,
        "modelo": "iPhone 15 Pro",
        "marca": "Apple",
        "capacidade": Capacidade(256),
        "condicao": Condicao.SEMINOVO,
        "preco": Dinheiro.de(Decimal("4200")),
    }
    return base | mudancas


def test_item_completo_e_ofertavel() -> None:
    assert motivo_nao_ofertavel(**_valido()) is None


@pytest.mark.parametrize(
    ("mudancas", "motivo"),
    [
        ({"preco": None}, MotivoDescarte.SEM_PRECO),
        ({"preco": Dinheiro.zero()}, MotivoDescarte.SEM_PRECO),
        ({"preco": Dinheiro.de(Decimal("0.01"))}, MotivoDescarte.SEM_PRECO),
        ({"preco": Dinheiro.de(Decimal("-5"))}, MotivoDescarte.SEM_PRECO),
        ({"quantidade": 0}, MotivoDescarte.SEM_QUANTIDADE),
        ({"quantidade": -2}, MotivoDescarte.SEM_QUANTIDADE),
        ({"disponivel": False}, MotivoDescarte.INDISPONIVEL),
        ({"condicao": None}, MotivoDescarte.ESTADO_NAO_INFORMADO),
        ({"e_celular": False}, MotivoDescarte.NAO_E_CELULAR),
        ({"capacidade": None}, MotivoDescarte.SEM_CAPACIDADE),
        ({"modelo": None}, MotivoDescarte.SEM_MODELO),
        ({"modelo": "   "}, MotivoDescarte.SEM_MODELO),
        ({"marca": None}, MotivoDescarte.MARCA_NAO_IDENTIFICADA),
        ({"marca": ""}, MotivoDescarte.MARCA_NAO_IDENTIFICADA),
    ],
)
def test_cada_regra_tem_motivo_tipado(mudancas: dict[str, Any], motivo: MotivoDescarte) -> None:
    assert motivo_nao_ofertavel(**_valido(**mudancas)) is motivo


def test_preco_de_um_centavo_e_sem_preco_mas_dois_centavos_e_ofertavel() -> None:
    um = _valido(preco=Dinheiro.de(Decimal("0.01")))
    dois = _valido(preco=Dinheiro.de(Decimal("0.02")))
    assert motivo_nao_ofertavel(**um) is MotivoDescarte.SEM_PRECO
    assert motivo_nao_ofertavel(**dois) is None


def test_categoria_que_nao_e_celular_prevalece_sobre_os_demais_defeitos() -> None:
    dados = _valido(e_celular=False, preco=None, capacidade=None, disponivel=False)
    assert motivo_nao_ofertavel(**dados) is MotivoDescarte.NAO_E_CELULAR


def test_motivos_sao_strings_estaveis_para_relatorio() -> None:
    assert MotivoDescarte.SEM_PRECO.value == "sem_preco"
    assert {m.value for m in MotivoDescarte} >= {
        "sem_preco",
        "sem_quantidade",
        "indisponivel",
        "estado_nao_informado",
        "nao_e_celular",
        "sem_capacidade",
        "sem_modelo",
    }
