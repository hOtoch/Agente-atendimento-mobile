from __future__ import annotations

from decimal import Decimal

from app.application.llm import UsoTokens
from evals.precos import PRECOS, custo_usd, estimar_custo


def test_precos_oficiais_do_projeto() -> None:
    sonnet, haiku = PRECOS["claude-sonnet-5-5"], PRECOS["claude-haiku-5-5"]
    assert (sonnet.entrada, sonnet.saida) == (Decimal("2.00"), Decimal("10.00"))
    assert (sonnet.cache_leitura, sonnet.cache_escrita) == (Decimal("0.10"), Decimal("2.50"))
    assert (haiku.entrada, haiku.saida) == (Decimal("0.10"), Decimal("0.50"))
    assert (haiku.cache_leitura, haiku.cache_escrita) == (Decimal("0.01"), Decimal("0.125"))


def test_custo_usd_soma_as_quatro_parcelas() -> None:
    uso = UsoTokens("claude-sonnet-5-5", 1_000_000, 100_000, 2_000_000, 400_000)
    # 2,00 + 1,00 + 0,20 + 1,00
    assert custo_usd(uso) == Decimal("4.20")


def test_custo_usd_modelo_sem_preco_e_none() -> None:
    assert custo_usd(UsoTokens("fake", 10, 10, 0, 0)) is None


def test_estimar_custo_cresce_com_cenarios_e_turnos() -> None:
    um = estimar_custo("claude-sonnet-5-5", "claude-haiku-5-5", cenarios=1, turnos=1)
    quinze = estimar_custo("claude-sonnet-5-5", "claude-haiku-5-5", cenarios=15, turnos=12)
    assert um.total > 0
    assert quinze.total == um.total * 15 * 12
    assert quinze.agente > quinze.cliente > 0
