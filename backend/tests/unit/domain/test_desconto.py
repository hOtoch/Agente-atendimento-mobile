from datetime import date, timedelta
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.domain.desconto import (
    DescontoLiberado,
    EstadoDesconto,
    MotivoPassagem,
    PassarAoVendedor,
    PedidoCliente,
    PoliticaDesconto,
    RegraOportunidadeUnica,
    TetoAtingido,
    decidir_pedido_desconto,
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


# --- escada de desconto: decidir_pedido_desconto --------------------------


def _pedir_ate_vendedor(
    politica: PoliticaDesconto, pedido: PedidoCliente = PedidoCliente.MAIS_DESCONTO
) -> list[DescontoLiberado | PassarAoVendedor]:
    estado = EstadoDesconto()
    saidas: list[DescontoLiberado | PassarAoVendedor] = []
    for _ in range(3000):
        decisao = decidir_pedido_desconto(politica, estado, pedido)
        saidas.append(decisao)
        if isinstance(decisao, PassarAoVendedor):
            return saidas
        estado = decisao.estado
    raise AssertionError("nunca passou ao vendedor")


def test_escada_50_100_libera_50_depois_100_depois_vendedor() -> None:
    politica = PoliticaDesconto(teto=din(100), degrau=din(50))
    primeiro, segundo, terceiro = _pedir_ate_vendedor(politica)
    assert isinstance(primeiro, DescontoLiberado) and primeiro.total == din(50)
    assert isinstance(segundo, DescontoLiberado) and segundo.total == din(100)
    assert segundo.estado == EstadoDesconto(liberado=din(100))
    assert terceiro == PassarAoVendedor(MotivoPassagem.ACIMA_DO_TETO, din(100))


def test_brinde_passa_ao_vendedor_em_qualquer_momento() -> None:
    politica = PoliticaDesconto(teto=din(100), degrau=din(50))
    for liberado in (0, 50, 100):
        decisao = decidir_pedido_desconto(
            politica, EstadoDesconto(liberado=din(liberado)), PedidoCliente.BRINDE_OU_BENEFICIO
        )
        assert decisao == PassarAoVendedor(MotivoPassagem.BRINDE_OU_BENEFICIO, din(liberado))


def test_teto_zero_passa_ao_vendedor_no_primeiro_pedido() -> None:
    politica = PoliticaDesconto(teto=Dinheiro.zero(), degrau=din(50))
    decisao = decidir_pedido_desconto(politica, EstadoDesconto(), PedidoCliente.MAIS_DESCONTO)
    assert decisao == PassarAoVendedor(MotivoPassagem.ACIMA_DO_TETO, Dinheiro.zero())


def test_motivos_de_passagem_tem_valor_estavel() -> None:
    assert MotivoPassagem.ACIMA_DO_TETO.value == "acima_do_teto"
    assert MotivoPassagem.BRINDE_OU_BENEFICIO.value == "brinde_ou_beneficio"


@given(teto=st.integers(0, 2000), degrau=st.integers(1, 500))
def test_propriedade_soma_liberada_nunca_passa_do_teto(teto: int, degrau: int) -> None:
    politica = PoliticaDesconto(teto=din(teto), degrau=din(degrau))
    saidas = _pedir_ate_vendedor(politica)
    for s in saidas:
        if isinstance(s, DescontoLiberado):
            assert s.total <= politica.teto
            assert s.estado.liberado == s.total
    assert saidas[-1].liberado == politica.teto  # type: ignore[union-attr]


@given(teto=st.integers(0, 2000), degrau=st.integers(1, 500))
def test_propriedade_pedidos_ate_o_vendedor_e_teto_sobre_degrau_mais_um(
    teto: int, degrau: int
) -> None:
    politica = PoliticaDesconto(teto=din(teto), degrau=din(degrau))
    assert len(_pedir_ate_vendedor(politica)) == -(-teto // degrau) + 1
