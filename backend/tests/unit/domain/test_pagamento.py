from decimal import Decimal

import pytest

from app.domain.pagamento import (
    DEBITO,
    AvisoProposta,
    Credito,
    Debito,
    DescontoPixNenhum,
    DescontoPixPercentual,
    DescontoPixValor,
    EntradaMaisCredito,
    EntradaNaoAceita,
    PagamentoError,
    ParcelasAcimaDoMaximo,
    ParcelasInvalidas,
    PixDinheiro,
    RegrasPreco,
    TabelaTaxas,
    TaxaNaoCadastrada,
    calcular_pagamento,
    simular_opcoes,
)
from app.domain.valores import Bandeira, Dinheiro

MASTER = {
    1: "3.44", 2: "4.65", 3: "5.44", 4: "6.36", 5: "7.15", 6: "7.99",
    7: "9.33", 8: "9.34", 9: "9.58", 10: "9.59", 11: "10.53", 12: "10.54",
    13: "12.69", 14: "13.44", 15: "14.19", 16: "14.94", 17: "15.03", 18: "15.04",
}  # fmt: skip


def tabela() -> TabelaTaxas:
    taxas: dict[tuple[int | str, Bandeira], Decimal | None] = {
        (n, Bandeira.MASTERCARD): Decimal(t) for n, t in MASTER.items()
    }
    taxas[(DEBITO, Bandeira.MASTERCARD)] = Decimal("1.99")
    taxas[(DEBITO, Bandeira.VISA)] = Decimal("1.89")
    taxas[(12, Bandeira.VISA)] = Decimal("11.00")
    taxas[(12, Bandeira.ELO)] = None  # "igual" -> Mastercard
    return TabelaTaxas(taxas)  # type: ignore[arg-type]


def regras(**kw: object) -> RegrasPreco:
    base: dict[str, object] = {
        "max_parcelas": 18,
        "repassa_taxa": True,
        "desconto_pix": DescontoPixNenhum(),
        "aceita_entrada_mais_cartao": True,
    }
    base.update(kw)
    return RegrasPreco(**base)  # type: ignore[arg-type]


def d(v: str | int) -> Dinheiro:
    return Dinheiro.de(v)


Z = Dinheiro.zero()


def test_exemplo_oficial_12x_mastercard() -> None:
    p = calcular_pagamento(d(4830), Z, Z, Credito(12, Bandeira.MASTERCARD), regras(), tabela())
    assert p.valor_parcela == d("444.92")
    assert p.parcelas == 12
    assert p.base == d(4830)
    assert p.taxa_aplicada_pct == Decimal("10.54")
    assert p.total_pago == d("444.92") * 12
    assert p.aviso is None


def test_base_desconta_desconto_e_troca() -> None:
    p = calcular_pagamento(
        d(5000), d(100), d(70), Credito(1, Bandeira.MASTERCARD), regras(), tabela()
    )
    assert p.base == d(4830)
    assert p.valor_parcela == d("4996.15")  # 4830 * 1.0344


def test_parcelas_acima_do_maximo() -> None:
    with pytest.raises(ParcelasAcimaDoMaximo):
        calcular_pagamento(
            d(1000), Z, Z, Credito(13, Bandeira.MASTERCARD), regras(max_parcelas=12), tabela()
        )


@pytest.mark.parametrize("n", [0, -1, 22])
def test_parcelas_invalidas(n: int) -> None:
    with pytest.raises(ParcelasInvalidas):
        calcular_pagamento(
            d(1000), Z, Z, Credito(n, Bandeira.MASTERCARD), regras(max_parcelas=30), tabela()
        )


def test_sem_repasse_parcela_e_valor_dividido() -> None:
    p = calcular_pagamento(
        d(4830), Z, Z, Credito(12, Bandeira.MASTERCARD), regras(repassa_taxa=False), tabela()
    )
    assert p.valor_parcela == d("402.50")
    assert p.taxa_aplicada_pct == Decimal(0)
    assert p.total_pago == d(4830)


def test_sem_repasse_debito_nao_cobra_taxa() -> None:
    p = calcular_pagamento(
        d(1000), Z, Z, Debito(Bandeira.MASTERCARD), regras(repassa_taxa=False), tabela()
    )
    assert p.total_pago == d(1000)


def test_entrada_mais_cartao_aceita() -> None:
    forma = EntradaMaisCredito(d(1000), 10, Bandeira.MASTERCARD)
    p = calcular_pagamento(d(5000), Z, d(500), forma, regras(), tabela())
    assert p.entrada == d(1000)
    assert p.base == d(3500)
    assert p.parcelas == 10
    assert p.valor_parcela == d("383.57")  # 3500 * 1.0959 / 10
    assert p.total_pago == d(1000) + p.valor_parcela * 10


def test_entrada_mais_cartao_recusada() -> None:
    forma = EntradaMaisCredito(d(1000), 10, Bandeira.MASTERCARD)
    with pytest.raises(EntradaNaoAceita):
        calcular_pagamento(d(5000), Z, Z, forma, regras(aceita_entrada_mais_cartao=False), tabela())


def test_bandeira_igual_usa_mastercard() -> None:
    p = calcular_pagamento(d(4830), Z, Z, Credito(12, Bandeira.ELO), regras(), tabela())
    assert p.valor_parcela == d("444.92")
    # ausencia total da bandeira tambem e "igual"
    p2 = calcular_pagamento(d(4830), Z, Z, Credito(12, Bandeira.AMEX), regras(), tabela())
    assert p2.valor_parcela == d("444.92")


def test_bandeira_com_taxa_propria() -> None:
    assert tabela().taxa(12, Bandeira.VISA) == Decimal("11.00")


def test_taxa_nao_cadastrada() -> None:
    with pytest.raises(TaxaNaoCadastrada):
        tabela().taxa(19, Bandeira.MASTERCARD)
    with pytest.raises(TaxaNaoCadastrada):
        TabelaTaxas({}).taxa(DEBITO, Bandeira.VISA)


def test_erros_tem_base_comum() -> None:
    for erro in (ParcelasAcimaDoMaximo, EntradaNaoAceita, TaxaNaoCadastrada, ParcelasInvalidas):
        assert issubclass(erro, PagamentoError)


def test_troca_maior_que_o_preco() -> None:
    p = calcular_pagamento(
        d(3000), Z, d(4000), Credito(12, Bandeira.MASTERCARD), regras(), tabela()
    )
    assert p.base == Z
    assert p.valor_parcela == Z
    assert p.total_pago == Z
    assert p.aviso is AvisoProposta.TROCA_COBRE_O_VALOR


def test_pix_sem_desconto_e_o_proprio_preco() -> None:
    p = calcular_pagamento(d(4830), Z, Z, PixDinheiro(), regras(), tabela())
    assert p.total_pago == d(4830)
    assert p.parcelas == 1
    assert p.valor_parcela == d(4830)
    assert p.taxa_aplicada_pct == Decimal(0)


def test_pix_com_desconto_percentual() -> None:
    r = regras(desconto_pix=DescontoPixPercentual(Decimal(5)))
    p = calcular_pagamento(d(4830), Z, Z, PixDinheiro(), r, tabela())
    assert p.base == d(4830)
    assert p.total_pago == d("4588.50")


def test_pix_com_desconto_em_valor() -> None:
    r = regras(desconto_pix=DescontoPixValor(d(150)))
    p = calcular_pagamento(d(4830), Z, Z, PixDinheiro(), r, tabela())
    assert p.total_pago == d(4680)


def test_pix_desconto_em_valor_nao_deixa_negativo() -> None:
    r = regras(desconto_pix=DescontoPixValor(d(150)))
    p = calcular_pagamento(d(100), Z, Z, PixDinheiro(), r, tabela())
    assert p.total_pago == Z


def test_desconto_pix_nao_vale_no_cartao() -> None:
    r = regras(desconto_pix=DescontoPixPercentual(Decimal(5)))
    p = calcular_pagamento(d(1000), Z, Z, Credito(1, Bandeira.MASTERCARD), r, tabela())
    assert p.valor_parcela == d("1034.40")


def test_debito_usa_taxa_de_debito() -> None:
    p = calcular_pagamento(d(1000), Z, Z, Debito(Bandeira.MASTERCARD), regras(), tabela())
    assert p.parcelas == 1
    assert p.taxa_aplicada_pct == Decimal("1.99")
    assert p.total_pago == d("1019.90")
    p2 = calcular_pagamento(d(1000), Z, Z, Debito(Bandeira.VISA), regras(), tabela())
    assert p2.total_pago == d("1018.90")


def test_simular_opcoes_max_18() -> None:
    ops = simular_opcoes(d(4830), Z, Z, regras(max_parcelas=18), tabela())
    assert [(type(o.forma).__name__, o.parcelas) for o in ops] == [
        ("PixDinheiro", 1),
        ("Credito", 1),
        ("Credito", 10),
        ("Credito", 12),
        ("Credito", 18),
    ]
    assert ops[3].valor_parcela == d("444.92")


def test_simular_opcoes_max_10_sem_duplicata() -> None:
    ops = simular_opcoes(d(4830), Z, Z, regras(max_parcelas=10), tabela())
    assert [o.parcelas for o in ops] == [1, 1, 10]
    assert isinstance(ops[0].forma, PixDinheiro)
    assert all(o.parcelas <= 10 for o in ops)


def test_simular_opcoes_max_12_sem_duplicata() -> None:
    ops = simular_opcoes(d(4830), Z, Z, regras(max_parcelas=12), tabela())
    assert [o.parcelas for o in ops] == [1, 1, 10, 12]


def test_simular_opcoes_bandeira() -> None:
    ops = simular_opcoes(d(4830), Z, Z, regras(), tabela(), Bandeira.VISA)
    doze = next(o for o in ops if o.parcelas == 12)
    assert doze.taxa_aplicada_pct == Decimal("11.00")
