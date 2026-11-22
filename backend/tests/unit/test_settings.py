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


def test_settings_defaults_de_banco(monkeypatch: pytest.MonkeyPatch) -> None:
    for nome in ("DATABASE_URL", "TEST_DATABASE_URL"):
        monkeypatch.delenv(nome, raising=False)

    s = Settings(_env_file=None)

    assert (
        s.database_url == "postgresql+asyncpg://atendimento:atendimento@localhost:5432/atendimento"
    )
    assert s.test_database_url == "postgresql+asyncpg://teste:teste@localhost:5433/teste"


def test_settings_de_midia(monkeypatch: pytest.MonkeyPatch) -> None:
    for nome in ("MIDIA_DIR", "MIDIA_MAX_BYTES"):
        monkeypatch.delenv(nome, raising=False)
    padrao = Settings(_env_file=None)
    assert padrao.midia_dir == "./.midias"
    assert padrao.midia_max_bytes == 10 * 1024 * 1024

    monkeypatch.setenv("MIDIA_DIR", "/tmp/m")
    monkeypatch.setenv("MIDIA_MAX_BYTES", "1024")
    s = Settings(_env_file=None)
    assert (s.midia_dir, s.midia_max_bytes) == ("/tmp/m", 1024)


def test_settings_da_evolution(monkeypatch: pytest.MonkeyPatch) -> None:
    for nome in (
        "EVOLUTION_API_URL",
        "EVOLUTION_API_KEY",
        "EVOLUTION_WEBHOOK_URL",
        "EVOLUTION_WEBHOOK_TOKEN",
        "API_PUBLICA_URL",
        "WHATSAPP_ECO_GRACA_S",
    ):
        monkeypatch.delenv(nome, raising=False)
    padrao = Settings(_env_file=None)
    assert padrao.evolution_api_url == "http://localhost:8080"
    assert padrao.evolution_webhook_url == "http://host.docker.internal:8000/webhooks/evolution"
    assert padrao.api_publica_url == "http://localhost:8000"
    assert padrao.whatsapp_eco_graca_s == 0.5

    monkeypatch.setenv("EVOLUTION_API_KEY", "k")
    monkeypatch.setenv("EVOLUTION_WEBHOOK_TOKEN", "t")
    s = Settings(_env_file=None)
    assert (s.evolution_api_key, s.evolution_webhook_token) == ("k", "t")


def test_settings_de_stt(monkeypatch: pytest.MonkeyPatch) -> None:
    for nome in ("OPENAI_API_KEY", "STT_MODEL"):
        monkeypatch.delenv(nome, raising=False)
    padrao = Settings(_env_file=None)
    assert padrao.openai_api_key is None
    assert padrao.stt_model == "gpt-4o-mini-transcribe"

    monkeypatch.setenv("OPENAI_API_KEY", "sk-x")
    monkeypatch.setenv("STT_MODEL", "whisper-1")
    s = Settings(_env_file=None)
    assert (s.openai_api_key, s.stt_model) == ("sk-x", "whisper-1")


def test_settings_de_tts_sao_opcionais(monkeypatch: pytest.MonkeyPatch) -> None:
    for nome in ("OPENAI_API_KEY", "TTS_MODEL", "TTS_VOZ"):
        monkeypatch.delenv(nome, raising=False)

    s = Settings(_env_file=None)

    assert s.openai_api_key is None
    assert s.tts_model == "gpt-4o-mini-tts"
    assert s.tts_voz


def test_settings_mercadophone_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for nome in ("MERCADOPHONE_MCP_URL", "MERCADOPHONE_API_KEY"):
        monkeypatch.delenv(nome, raising=False)

    s = Settings(_env_file=None)

    assert s.mercadophone_mcp_url == "https://platform.mercadophone.tech/mcp/platform/"
    assert s.mercadophone_api_key is None


def test_settings_mercadophone_le_do_ambiente(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MERCADOPHONE_MCP_URL", "https://outro.test/mcp/")
    monkeypatch.setenv("MERCADOPHONE_API_KEY", "chave-teste")

    s = Settings(_env_file=None)

    assert s.mercadophone_mcp_url == "https://outro.test/mcp/"
    assert s.mercadophone_api_key == "chave-teste"
