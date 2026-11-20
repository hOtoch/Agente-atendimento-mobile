"""`scripts/conversar.py`: sem chave mostra mensagem clara; `--fake` fecha o fio (sem rede)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
SCRIPT = BACKEND / "scripts" / "conversar.py"


def _rodar(*args: str, entrada: str = "") -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "ANTHROPIC_API_KEY": ""}
    return subprocess.run(  # noqa: S603
        [sys.executable, str(SCRIPT), *args],
        cwd=BACKEND,
        input=entrada,
        capture_output=True,
        text=True,
        env=env,
        encoding="utf-8",
        timeout=60,
        check=False,
    )


def test_sem_chave_mostra_mensagem_clara_e_nao_quebra() -> None:
    r = _rodar()
    assert r.returncode == 2
    assert "ANTHROPIC_API_KEY" in r.stderr and "--fake" in r.stderr
    assert "Traceback" not in r.stderr


def test_fake_conversa_de_ponta_a_ponta() -> None:
    r = _rodar("--fake", entrada="oi, quero um iphone 16\n\n")
    assert r.returncode == 0, r.stderr
    assert "eco: oi, quero um iphone 16" in r.stdout
    assert "Novo contato" in r.stdout
