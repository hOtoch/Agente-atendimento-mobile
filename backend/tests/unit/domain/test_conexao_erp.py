"""Conexao da loja com o ERP: validacao de unidade e intervalo (funcao pura, sem IO)."""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.domain.conexao_erp import PROVEDOR_MERCADOPHONE, ConexaoErp, ConexaoErpInvalida


def conexao(**campos: object) -> ConexaoErp:
    base: dict[str, object] = {"loja_id": uuid4(), "system_unit_id": 7}
    return ConexaoErp(**{**base, **campos})  # type: ignore[arg-type]


def test_padroes() -> None:
    c = conexao()
    assert c.provedor == PROVEDOR_MERCADOPHONE == "mercadophone"
    assert (c.ativo, c.intervalo_min, c.exportar_handoff) == (False, 15, False)
    assert c.filtro_loja is None
    assert (c.ultima_sincronizacao_em, c.ultimo_status, c.ultimo_relatorio) == (None, None, None)


@pytest.mark.parametrize("valor", [0, -1])
def test_unidade_precisa_ser_positiva(valor: int) -> None:
    with pytest.raises(ConexaoErpInvalida) as exc:
        conexao(system_unit_id=valor)
    assert exc.value.campo == "system_unit_id"


@pytest.mark.parametrize("valor", [5, 15, 1440])
def test_intervalo_nos_limites_valido(valor: int) -> None:
    assert conexao(intervalo_min=valor).intervalo_min == valor


@pytest.mark.parametrize("valor", [0, 4, 1441])
def test_intervalo_fora_de_5_a_1440_e_recusado(valor: int) -> None:
    with pytest.raises(ConexaoErpInvalida) as exc:
        conexao(intervalo_min=valor)
    assert exc.value.campo == "intervalo_min"


def test_filtro_vazio_vira_none_e_o_texto_e_aparado() -> None:
    assert conexao(filtro_loja="   ").filtro_loja is None
    assert conexao(filtro_loja="  Loja Centro ").filtro_loja == "Loja Centro"


def test_provedor_desconhecido_e_recusado() -> None:
    with pytest.raises(ConexaoErpInvalida) as exc:
        conexao(provedor="outro")
    assert exc.value.campo == "provedor"
