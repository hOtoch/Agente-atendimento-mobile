"""Tabela de precos e custo em US$ no dominio (Decimal, sem arredondar)."""

from __future__ import annotations

from decimal import Decimal

from app.domain.precos import PRECOS, Preco, custo_usd


def test_tabela_oficial_do_projeto() -> None:
    sonnet, haiku = PRECOS["claude-sonnet-5-5"], PRECOS["claude-haiku-5-5"]
    assert sonnet == Preco(Decimal("2.00"), Decimal("10.00"), Decimal("0.10"), Decimal("2.50"))
    assert haiku == Preco(Decimal("0.10"), Decimal("0.50"), Decimal("0.01"), Decimal("0.125"))


def test_tabela_tem_os_modelos_da_openai_sem_custo_de_escrita_de_cache() -> None:
    assert PRECOS["gpt-4.1-mini"] == Preco(
        Decimal("0.40"), Decimal("1.60"), Decimal("0.10"), Decimal(0)
    )
    assert PRECOS["gpt-4o-mini"] == Preco(
        Decimal("0.15"), Decimal("0.60"), Decimal("0.075"), Decimal(0)
    )


def test_custo_soma_as_quatro_parcelas() -> None:
    # 2,00 + 1,00 + 0,20 + 1,00
    custo = custo_usd("claude-sonnet-5-5", 1_000_000, 100_000, 2_000_000, 400_000)
    assert custo == Decimal("4.20")


def test_custo_nao_arredonda() -> None:
    # 489 x 2 + 174 x 10 + 10764 x 0,10 + 885 x 2,5 = 6006,9 / 1e6
    custo = custo_usd("claude-sonnet-5-5", 489, 174, 10_764, 885)
    assert custo == Decimal("0.0060069")


def test_modelo_sem_preco_nao_tem_custo() -> None:
    assert custo_usd("modelo-x", 10, 10, 0, 0) is None
    assert custo_usd("misto", 10, 10, 0, 0) is None


def test_uso_zerado_custa_zero() -> None:
    assert custo_usd("claude-haiku-5-5", 0, 0, 0, 0) == Decimal(0)
