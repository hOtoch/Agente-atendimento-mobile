from datetime import date, timedelta
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.domain.desconto import (
    EstadoDesconto,
    PoliticaDesconto,
    RegraOportunidadeUnica,
    TetoAtingido,
    desconto_total,
    liberar_proximo,
    oportunidade_unica,
)
from app.domain.valores import Dinheiro

HOJE = date(2026, 11, 19)


def din(valor: str | int) -> Dinheiro:
    return Dinheiro.de(valor)


def regra(
    *, ativa: bool = True, dias: int = 14, valor: int = 100, conta_no_teto: bool = False
) -> RegraOportunidadeUnica:
    return RegraOportunidadeUnica(
        ativa=ativa, dias_minimos=dias, valor=din(valor), conta_no_teto=conta_no_teto
    )


# --- politica / degraus -------------------------------------------------


def test_estado_inicial_zerado() -> None:
    assert EstadoDesconto().liberado == Dinheiro.zero()


def test_degraus_teto_100_de_50_em_50() -> None:
    politica = PoliticaDesconto(teto=din(100), degrau=din(50))
    estado = EstadoDesconto()

    r1 = liberar_proximo(politica, estado)
    assert not isinstance(r1, TetoAtingido)
    estado1, total1 = r1
    assert total1 == din(50)
    assert estado1.liberado == din(50)

    r2 = liberar_proximo(politica, estado1)
    assert not isinstance(r2, TetoAtingido)
    estado2, total2 = r2
    assert total2 == din(100)
    assert estado2.liberado == din(100)

    r3 = liberar_proximo(politica, estado2)
    assert r3 == TetoAtingido(total=din(100))


def test_liberar_proximo_nao_muta_estado() -> None:
    politica = PoliticaDesconto(teto=din(100), degrau=din(50))
    estado = EstadoDesconto()
    liberar_proximo(politica, estado)
    assert estado.liberado == Dinheiro.zero()


def test_teto_nao_multiplo_do_degrau_ultimo_degrau_parcial() -> None:
    politica = PoliticaDesconto(teto=din(120), degrau=din(50))
    estado = EstadoDesconto()
    totais = []
    for _ in range(3):
        r = liberar_proximo(politica, estado)
        assert not isinstance(r, TetoAtingido)
        estado, total = r
        totais.append(total)
    assert totais == [din(50), din(100), din(120)]
    assert liberar_proximo(politica, estado) == TetoAtingido(total=din(120))


def test_degrau_maior_que_teto_libera_o_teto() -> None:
    politica = PoliticaDesconto(teto=din(30), degrau=din(50))
    r = liberar_proximo(politica, EstadoDesconto())
    assert not isinstance(r, TetoAtingido)
    assert r[1] == din(30)


def test_teto_zero_ja_atingido() -> None:
    politica = PoliticaDesconto(teto=Dinheiro.zero(), degrau=din(50))
    assert liberar_proximo(politica, EstadoDesconto()) == TetoAtingido(total=Dinheiro.zero())


@pytest.mark.parametrize("degrau", ["0", "-10"])
def test_degrau_deve_ser_positivo(degrau: str) -> None:
    with pytest.raises(ValueError, match="degrau"):
        PoliticaDesconto(teto=din(100), degrau=din(degrau))


def test_teto_nao_pode_ser_negativo() -> None:
    with pytest.raises(ValueError, match="teto"):
        PoliticaDesconto(teto=din("-1"), degrau=din(50))


def test_regra_valida_parametros() -> None:
    with pytest.raises(ValueError, match="dias_minimos"):
        regra(dias=-1)
    with pytest.raises(ValueError, match="valor"):
        RegraOportunidadeUnica(ativa=True, dias_minimos=14, valor=din("-1"))


# --- oportunidade unica -------------------------------------------------


def test_14_dias_exatos_nao_disparam() -> None:
    assert oportunidade_unica(HOJE + timedelta(days=14), HOJE, regra()) is None


def test_15_dias_disparam() -> None:
    assert oportunidade_unica(HOJE + timedelta(days=15), HOJE, regra()) == din(100)


def test_data_passada_ou_hoje_retorna_none() -> None:
    assert oportunidade_unica(HOJE - timedelta(days=1), HOJE, regra()) is None
    assert oportunidade_unica(HOJE, HOJE, regra()) is None
    assert oportunidade_unica(HOJE, HOJE, regra(dias=0)) is None


def test_dias_minimos_zero_dispara_amanha() -> None:
    assert oportunidade_unica(HOJE + timedelta(days=1), HOJE, regra(dias=0)) == din(100)


def test_regra_inativa_retorna_none() -> None:
    assert oportunidade_unica(HOJE + timedelta(days=60), HOJE, regra(ativa=False)) is None


# --- desconto total -----------------------------------------------------


def test_sem_oportunidade_retorna_liberado() -> None:
    politica = PoliticaDesconto(teto=din(100), degrau=din(50))
    assert desconto_total(politica, EstadoDesconto(liberado=din(50)), None, regra()) == din(50)


def test_oportunidade_fora_do_teto_por_default() -> None:
    politica = PoliticaDesconto(teto=din(100), degrau=din(50))
    estado = EstadoDesconto(liberado=din(100))
    assert desconto_total(politica, estado, din(100), regra()) == din(200)


def test_oportunidade_conta_no_teto_limita_soma() -> None:
    politica = PoliticaDesconto(teto=din(100), degrau=din(50))
    r = regra(conta_no_teto=True)
    assert desconto_total(politica, EstadoDesconto(liberado=din(50)), din(100), r) == din(100)
    assert desconto_total(politica, EstadoDesconto(liberado=din(100)), din(100), r) == din(100)
    assert desconto_total(politica, EstadoDesconto(), din(30), r) == din(30)
    assert desconto_total(politica, EstadoDesconto(liberado=din(50)), din(30), r) == din(80)


# --- propriedade --------------------------------------------------------

centavos = st.integers(min_value=0, max_value=10**7)


def din_c(c: int) -> Dinheiro:
    return Dinheiro.de(Decimal(c) / 100)


@given(teto=centavos, degrau=st.integers(min_value=1, max_value=10**7), n=st.integers(0, 50))
def test_nunca_passa_do_teto_e_nao_decresce(teto: int, degrau: int, n: int) -> None:
    politica = PoliticaDesconto(teto=din_c(teto), degrau=din_c(degrau))
    estado = EstadoDesconto()
    anterior = Dinheiro.zero()
    for _ in range(n):
        r = liberar_proximo(politica, estado)
        if isinstance(r, TetoAtingido):
            assert r.total == estado.liberado == politica.teto
            break
        estado, total = r
        assert total >= anterior
        assert total <= politica.teto
        assert estado.liberado == total
        anterior = total
