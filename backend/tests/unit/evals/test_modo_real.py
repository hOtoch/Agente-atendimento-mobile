"""Modo real, mas SEMPRE com LLM mockado: prova a exigencia da flag e a estimativa."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.adapters.outbound.llm.fake import FakeLLM, RespostaRoteirizada
from app.application.llm import LLMPort
from evals import rodar


class FabricaEspia:
    def __init__(self, llms: dict[str, LLMPort]) -> None:
        self.modelos: list[str] = []
        self._llms = llms

    def __call__(self, modelo: str) -> LLMPort:
        self.modelos.append(modelo)
        return self._llms[modelo]


def test_sem_confirmo_custo_imprime_estimativa_e_sai_3_sem_chamar_nada(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    fabrica = FabricaEspia({})
    codigo = rodar.main(
        ["--modo", "real", "--modelo", "claude-sonnet-5-5", "--saida", str(tmp_path)],
        fabrica_llm=fabrica,
    )
    saida = capsys.readouterr().out
    assert codigo == 3
    assert "Estimativa de custo" in saida and "US$" in saida
    assert "--confirmo-custo" in saida
    assert fabrica.modelos == []
    assert list(tmp_path.iterdir()) == []


def test_modo_real_exige_modelo(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    assert rodar.main(["--modo", "real", "--saida", str(tmp_path)]) == 2
    assert "--modelo" in capsys.readouterr().err


def test_modelo_sem_preco_e_recusado(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    codigo = rodar.main(
        ["--modo", "real", "--modelo", "claude-desconhecido", "--saida", str(tmp_path)]
    )
    assert codigo == 2
    assert "preço" in capsys.readouterr().err


def test_com_confirmo_custo_roda_com_os_llms_da_fabrica(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    agente = FakeLLM([RespostaRoteirizada(texto="Oi! Qual iPhone você procura?")])
    cliente = FakeLLM([RespostaRoteirizada(texto="[FIM]")])
    fabrica = FabricaEspia({"claude-sonnet-5-5": agente, "claude-haiku-5-5": cliente})
    codigo = rodar.main(
        [
            "--modo", "real", "--modelo", "claude-sonnet-5-5", "--cenarios", "so_oi",
            "--confirmo-custo", "--saida", str(tmp_path), "--data", "2026-11-20",
        ],
        fabrica_llm=fabrica,
    )  # fmt: skip
    assert codigo == 0, capsys.readouterr()
    assert fabrica.modelos == ["claude-sonnet-5-5", "claude-haiku-5-5"]
    assert len(agente.chamadas) == 1 and len(cliente.chamadas) == 1
    assert (tmp_path / "2026-11-20-real-claude-sonnet-5-5.md").exists()
    assert (tmp_path / "2026-11-20-real-claude-sonnet-5-5.json").exists()
