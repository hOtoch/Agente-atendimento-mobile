"""A fixture `db_url` pula (local) ou falha (CI, EXIGIR_INTEGRACAO=1) quando o banco esta fora."""

from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[2]
CONFTEST = BACKEND_DIR / "tests" / "integration" / "conftest.py"
PORTA_FECHADA = "postgresql+asyncpg://teste:teste@localhost:5999/teste"


@pytest.fixture
def projeto(pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch) -> pytest.Pytester:
    monkeypatch.setenv("TEST_DATABASE_URL", PORTA_FECHADA)
    monkeypatch.setenv("PYTHONPATH", str(BACKEND_DIR))
    monkeypatch.setenv("PYTHONIOENCODING", "utf-8")
    pytester.makeini("[pytest]\nasyncio_mode = auto\n")
    pytester.makeconftest(CONFTEST.read_text(encoding="utf-8"))
    pytester.makepyfile(test_banco="async def test_usa_banco(db_url):\n    assert db_url\n")
    return pytester


def test_sem_exigir_integracao_pula(
    projeto: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("EXIGIR_INTEGRACAO", raising=False)
    resultado = projeto.runpytest_subprocess()
    resultado.assert_outcomes(skipped=1)


def test_com_exigir_integracao_falha_com_mensagem_clara(
    projeto: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EXIGIR_INTEGRACAO", "1")
    resultado = projeto.runpytest_subprocess()
    resultado.assert_outcomes(errors=1)  # pytest.fail na fixture conta como erro de setup
    resultado.stdout.fnmatch_lines(["*EXIGIR_INTEGRACAO=1*Postgres de teste inacessivel*"])
