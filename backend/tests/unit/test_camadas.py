"""Prova que o contrato de camadas (import-linter) detecta violacoes de verdade."""

import shutil
import subprocess
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]

# `-c` poe o cwd no sys.path, entao o pacote `app` do cwd vence o instalado.
_LINT = "from importlinter.cli import lint_imports_command; lint_imports_command()"


def _lint(cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        [sys.executable, "-c", _LINT],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


def test_pacote_real_respeita_o_contrato() -> None:
    resultado = _lint(BACKEND_DIR)
    assert resultado.returncode == 0, resultado.stdout + resultado.stderr


def test_import_proibido_no_dominio_quebra_o_lint_imports(tmp_path: Path) -> None:
    shutil.copytree(
        BACKEND_DIR / "app", tmp_path / "app", ignore=shutil.ignore_patterns("__pycache__")
    )
    shutil.copy(BACKEND_DIR / "pyproject.toml", tmp_path / "pyproject.toml")
    (tmp_path / "app" / "domain" / "violacao.py").write_text(
        "from app.infra import settings\n\n__all__ = ['settings']\n", encoding="utf-8"
    )

    resultado = _lint(tmp_path)

    assert resultado.returncode != 0, resultado.stdout + resultado.stderr
    assert "violacao" in resultado.stdout
