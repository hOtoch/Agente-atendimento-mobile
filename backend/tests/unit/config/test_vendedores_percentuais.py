from decimal import Decimal

from app.application.config.validacao import validar_pesos_vendedores


def test_pesos_dentro_de_0_a_100_sem_erro() -> None:
    assert validar_pesos_vendedores([Decimal(0), Decimal("50.5"), Decimal(100)]) == []


def test_pesos_fora_de_0_a_100_viram_erro_de_campo() -> None:
    erros = validar_pesos_vendedores([Decimal(10), Decimal(-1), Decimal("100.01")])
    assert [e.caminho for e in erros] == [
        "vendedores[1].peso_percentual",
        "vendedores[2].peso_percentual",
    ]
