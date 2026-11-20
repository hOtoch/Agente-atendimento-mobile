import pytest

from app.infra.settings import Settings


def test_settings_le_variaveis_de_ambiente(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@h/db")
    monkeypatch.setenv("REDIS_URL", "redis://h:6379/1")
    monkeypatch.setenv("LLM_MODEL", "modelo-x")
    monkeypatch.setenv("LLM_FALLBACK_MODEL", "modelo-y")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "chave-teste")

    s = Settings()

    assert s.database_url == "postgresql+asyncpg://u:p@h/db"
    assert s.redis_url == "redis://h:6379/1"
    assert s.llm_model == "modelo-x"
    assert s.llm_fallback_model == "modelo-y"
    assert s.anthropic_api_key == "chave-teste"


def test_settings_defaults_de_modelo(monkeypatch: pytest.MonkeyPatch) -> None:
    for nome in ("LLM_MODEL", "LLM_FALLBACK_MODEL", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(nome, raising=False)

    s = Settings(_env_file=None)

    assert s.llm_model == "claude-sonnet-5-5"
    assert s.llm_fallback_model == "claude-haiku-5-5"
    assert s.anthropic_api_key is None
