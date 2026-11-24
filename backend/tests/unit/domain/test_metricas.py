"""Periodo (fuso America/Sao_Paulo), variacao % e classificacao do motivo de handoff."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.domain.metricas import (
    FUSO,
    FUSO_NOME,
    MotivoHandoff,
    Periodo,
    classificar_motivo_handoff,
    razao,
    taxa_cache,
    variacao_pct,
)


def test_periodo_inclui_os_dois_extremos() -> None:
    p = Periodo(date(2026, 11, 1), date(2026, 11, 7))
    assert p.dias == 7
    assert p.listar_dias()[0] == date(2026, 11, 1)
    assert p.listar_dias()[-1] == date(2026, 11, 7)
    assert len(p.listar_dias()) == 7


def test_periodo_anterior_tem_o_mesmo_tamanho_e_termina_na_vespera() -> None:
    p = Periodo(date(2026, 11, 8), date(2026, 11, 14))
    anterior = p.anterior()
    assert anterior == Periodo(date(2026, 11, 1), date(2026, 11, 7))
    assert anterior.dias == p.dias


def test_limites_em_sao_paulo_convertidos_para_utc() -> None:
    p = Periodo(date(2026, 11, 9), date(2026, 11, 9))  # UTC-3 (sem horario de verao)
    assert p.inicio.astimezone(UTC) == datetime(2026, 11, 9, 3, 0, tzinfo=UTC)
    assert p.fim_exclusivo.astimezone(UTC) == datetime(2026, 11, 10, 3, 0, tzinfo=UTC)


def test_fuso_e_utc_menos_3_fixo_sem_depender_do_tzdata() -> None:
    # ZoneInfo exige a base de fusos do sistema (ou o pacote tzdata): no Windows a API nem sobe.
    # Sao Paulo nao tem horario de verao desde 2019, entao o deslocamento fixo e equivalente.
    assert type(FUSO) is timezone
    assert FUSO.utcoffset(None) == timedelta(hours=-3)
    assert FUSO_NOME == "America/Sao_Paulo"  # o nome segue indo para o Postgres e para a API


def test_periodo_invertido_e_recusado() -> None:
    with pytest.raises(ValueError, match="de"):
        Periodo(date(2026, 11, 9), date(2026, 11, 8))


@pytest.mark.parametrize(
    ("atual", "anterior", "esperado"),
    [
        (Decimal(150), Decimal(100), Decimal("50.0")),
        (Decimal(50), Decimal(100), Decimal("-50.0")),
        (Decimal(0), Decimal(0), Decimal("0.0")),
        (Decimal(10), Decimal(0), None),  # nao existe % sobre zero
        (None, Decimal(10), None),
        (Decimal(10), None, None),
        (Decimal(1), Decimal(3), Decimal("-66.7")),
    ],
)
def test_variacao_percentual(
    atual: Decimal | None, anterior: Decimal | None, esperado: Decimal | None
) -> None:
    assert variacao_pct(atual, anterior) == esperado


def test_razao_sem_denominador_e_none() -> None:
    assert razao(3, 4) == Decimal("0.75")
    assert razao(3, 0) is None
    assert razao(Decimal("1.5"), 2) == Decimal("0.75")


def test_taxa_de_cache_e_a_fatia_lida_do_cache_no_prompt() -> None:
    # 9000 lidos do cache de (500 novos + 9000 lidos + 500 escritos)
    assert taxa_cache(entrada=500, cache_leitura=9000, cache_escrita=500) == Decimal("0.9")
    assert taxa_cache(entrada=0, cache_leitura=0, cache_escrita=0) is None


@pytest.mark.parametrize(
    ("motivo", "esperado"),
    [
        ("acordo_fechado", MotivoHandoff.ACORDO_FECHADO),
        ("falha_llm", MotivoHandoff.FALHA_TECNICA),
        ("negociacao", MotivoHandoff.NEGOCIACAO),
        ("Negociacao", MotivoHandoff.NEGOCIACAO),
        ("Cliente pediu para falar com um atendente", MotivoHandoff.PEDIDO_CLIENTE),
        ("O cliente quer falar com uma pessoa", MotivoHandoff.PEDIDO_CLIENTE),
        ("Pedido do cliente: humano", MotivoHandoff.PEDIDO_CLIENTE),
        ("Cliente quer negociar desconto acima do teto", MotivoHandoff.OUTROS),
        ("", MotivoHandoff.OUTROS),
    ],
)
def test_classifica_o_motivo_do_handoff(motivo: str, esperado: MotivoHandoff) -> None:
    assert classificar_motivo_handoff(motivo) is esperado


def test_nomes_de_exibicao_dos_motivos() -> None:
    assert MotivoHandoff.PEDIDO_CLIENTE.nome_exibicao == "Pedido do cliente"
    assert MotivoHandoff.ACORDO_FECHADO.nome_exibicao == "Acordo fechado"
    assert MotivoHandoff.FALHA_TECNICA.nome_exibicao == "Falha técnica"
    assert MotivoHandoff.NEGOCIACAO.nome_exibicao == "Negociação além do teto"
    assert MotivoHandoff.OUTROS.nome_exibicao == "Outros"
