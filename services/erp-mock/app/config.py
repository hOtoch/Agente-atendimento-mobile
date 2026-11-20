from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuracao via env (prefixo ERP_MOCK_): TOKEN, LATENCIA_MS, ERRO_PCT, SEED."""

    model_config = SettingsConfigDict(env_prefix="ERP_MOCK_")

    token: str = "token-dev"
    latencia_ms: int = Field(default=0, ge=0)
    erro_pct: float = Field(default=0.0, ge=0, le=100)
    seed: int | None = None
