from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuracao lida do ambiente e do `.env` na raiz do repositorio."""

    # `../.env` (raiz do repo, rodando de backend/) e `.env` (rodando da raiz); o ultimo vence.
    model_config = SettingsConfigDict(
        env_file=("../.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/atendimento"
    redis_url: str = "redis://localhost:6379/0"
    llm_model: str = "claude-sonnet-5-5"
    llm_fallback_model: str = "claude-haiku-5-5"
    anthropic_api_key: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
