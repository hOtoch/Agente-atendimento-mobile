"""`scripts/custos.py`: custo por conversa a partir do usage, projecao 1k/10k e o markdown."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from app.application.llm import UsoTokens
from tests.unit.scripts.carregar import BACKEND, carregar_custos

custos = carregar_custos()

SONNET = "claude-sonnet-5-5"
HAIKU = "claude-haiku-5-5"


def _relatorio(modelo: str, usos: list[tuple[int, int, int, int]], tmp: Path) -> Path:
    cenarios = [
        {
            "id": f"c{i}",
            "aprovado": True,
            "deve_reprovar": False,
            "uso_agente": {
                "modelo": modelo,
                "entrada": e,
                "saida": s,
                "cache_leitura": cl,
                "cache_escrita": ce,
            },
            "uso_cliente": {
                "modelo": HAIKU,
                "entrada": 0,
                "saida": 0,
                "cache_leitura": 0,
                "cache_escrita": 0,
            },
        }
        for i, (e, s, cl, ce) in enumerate(usos)
    ]
    dados: dict[str, Any] = {
        "data": "2026-11-21",
        "modo": "real",
        "modelo": modelo,
        "modelo_cliente": HAIKU,
        "total_cenarios": len(cenarios),
        "aprovados": len(cenarios) - 1,
        "cenarios": cenarios,
    }
    caminho = tmp / f"{modelo}.json"
    caminho.write_text(json.dumps(dados), encoding="utf-8")
    return caminho


# --- custo de uma conversa a partir do usage -----------------------------------------------


def test_custo_da_conversa_soma_as_quatro_parcelas_com_a_tabela_de_precos() -> None:
    uso = UsoTokens(SONNET, 1_000_000, 100_000, 2_000_000, 400_000)
    assert custos.custo_conversa([uso]) == Decimal("4.20")


def test_custo_da_conversa_soma_modelos_diferentes_do_fallback() -> None:
    a = UsoTokens(SONNET, 1_000_000, 0, 0, 0)  # 2,00
    b = UsoTokens(HAIKU, 1_000_000, 0, 0, 0)  # 0,10
    assert custos.custo_conversa([a, b]) == Decimal("2.10")


def test_modelo_sem_preco_levanta_erro_claro() -> None:
    with pytest.raises(custos.ModeloSemPreco, match="modelo-x"):
        custos.custo_conversa([UsoTokens("modelo-x", 1, 1, 0, 0)])


def test_resumo_media_p50_maximo_e_tokens_medios() -> None:
    conversas = [
        [UsoTokens(HAIKU, 1_000_000, 0, 0, 0)],  # 0,10
        [UsoTokens(HAIKU, 2_000_000, 0, 0, 0)],  # 0,20
        [UsoTokens(HAIKU, 6_000_000, 0, 0, 0)],  # 0,60
    ]
    r = custos.resumir(conversas)
    assert r.conversas == 3
    assert r.media == Decimal("0.30")
    assert r.p50 == Decimal("0.20")
    assert r.maximo == Decimal("0.60")
    assert r.tokens_medios.entrada == 3_000_000


def test_resumo_sem_conversas_levanta_erro() -> None:
    with pytest.raises(ValueError, match="nenhuma conversa"):
        custos.resumir([])


# --- leitura do relatorio do eval ------------------------------------------------------------


def test_le_o_usage_do_agente_de_cada_cenario(tmp_path: Path) -> None:
    caminho = _relatorio(SONNET, [(100, 10, 1000, 50), (200, 20, 2000, 0)], tmp_path)
    fonte = custos.ler_relatorio_eval(caminho)
    assert fonte.modelo == SONNET
    assert fonte.data == "2026-11-21"
    assert (fonte.cenarios, fonte.aprovados) == (2, 1)
    assert fonte.conversas == [
        [UsoTokens(SONNET, 100, 10, 1000, 50)],
        [UsoTokens(SONNET, 200, 20, 2000, 0)],
    ]


def test_relatorio_fake_sem_preco_e_recusado(tmp_path: Path) -> None:
    caminho = _relatorio("fake", [(1, 1, 0, 0)], tmp_path)
    with pytest.raises(custos.ModeloSemPreco):
        custos.resumir(custos.ler_relatorio_eval(caminho).conversas)


def test_numeros_batem_com_o_custo_medido_dos_relatorios_reais_versionados() -> None:
    pasta = BACKEND / "evals" / "relatorios"
    for modelo in (HAIKU, SONNET):
        caminho = pasta / f"2026-11-21-real-{modelo}.json"
        medido = json.loads(caminho.read_text(encoding="utf-8"))["custo"]["por_conversa_agente"]
        resumo = custos.resumir(custos.ler_relatorio_eval(caminho).conversas)
        assert str(resumo.media.quantize(Decimal("0.000001"))) == medido["media"]
        assert str(resumo.p50.quantize(Decimal("0.000001"))) == medido["p50"]
        assert str(resumo.maximo.quantize(Decimal("0.000001"))) == medido["maximo"]


# --- audio, infra e projecao -----------------------------------------------------------------


def test_custo_de_audio_por_conversa_usa_as_premissas() -> None:
    p = custos.Premissas(
        pct_conversas_com_audio=Decimal("0.5"),
        minutos_stt_por_conversa_com_audio=Decimal("2"),
        minutos_tts_por_conversa_com_audio=Decimal("1"),
        usd_stt_por_minuto=Decimal("0.003"),
        usd_tts_por_minuto=Decimal("0.015"),
    )
    # 0,5 x (2 x 0,003 + 1 x 0,015) = 0,0105
    assert custos.custo_audio_por_conversa(p) == Decimal("0.0105")


def test_projecao_multiplica_por_leads_e_soma_llm_audio_e_infra() -> None:
    p = custos.Premissas(
        pct_conversas_com_audio=Decimal("0"),
        infra_usd_mes={1_000: (Decimal(20), Decimal(50)), 10_000: (Decimal(40), Decimal(100))},
    )
    proj = custos.projetar(Decimal("0.004"), leads=10_000, premissas=p)
    assert proj.llm == Decimal("40.00")
    assert proj.audio == Decimal("0.00")
    assert (proj.infra_min, proj.infra_max) == (Decimal(40), Decimal(100))
    assert (proj.total_min, proj.total_max) == (Decimal("80.00"), Decimal("140.00"))
    assert proj.por_lead_min == Decimal("0.008")


def test_projecao_com_volume_sem_faixa_de_infra_levanta_erro() -> None:
    with pytest.raises(KeyError):
        custos.projetar(Decimal("0.01"), leads=123, premissas=custos.Premissas())


def test_efeito_do_cache_compara_com_o_mesmo_uso_sem_cache() -> None:
    uso = UsoTokens(SONNET, 0, 0, 1_000_000, 0)  # cache lido: 0,10 contra 2,00 sem cache
    com, sem = custos.efeito_do_cache([[uso]])
    assert (com, sem) == (Decimal("0.10"), Decimal("2.00"))


# --- markdown --------------------------------------------------------------------------------


def test_markdown_traz_secoes_tabela_1k_10k_e_premissas(tmp_path: Path) -> None:
    fontes = [
        custos.ler_relatorio_eval(_relatorio(HAIKU, [(1000, 100, 100_000, 5000)], tmp_path)),
        custos.ler_relatorio_eval(_relatorio(SONNET, [(1000, 100, 100_000, 5000)], tmp_path)),
    ]
    md = custos.gerar_markdown(fontes, custos.Premissas())
    assert md.startswith("# Custos")
    for trecho in ("## Custo medido por conversa", "1 mil leads/mês", "10 mil leads/mês"):
        assert trecho in md
    assert "## Premissas" in md and "estimativa" in md.lower()
    assert "uv run python scripts/custos.py" in md
    assert "claude-haiku-5-5" in md and "claude-sonnet-5-5" in md
    # o texto nao inventa numero: o custo do Haiku da fixture aparece com 6 casas
    haiku = custos.resumir(fontes[0].conversas).media.quantize(Decimal("0.000001"))
    assert f"US$ {haiku}".replace(".", ",") in md


def test_main_escreve_o_arquivo_a_partir_dos_relatorios(tmp_path: Path) -> None:
    rel = _relatorio(HAIKU, [(1000, 100, 100_000, 5000)], tmp_path)
    saida = tmp_path / "custos.md"
    assert custos.main(["--relatorios", str(rel), "--saida", str(saida)]) == 0
    assert saida.read_text(encoding="utf-8").startswith("# Custos")


def test_main_sem_fonte_falha_com_mensagem(capsys: pytest.CaptureFixture[str]) -> None:
    assert custos.main([]) == 2
    assert "--relatorios" in capsys.readouterr().err
