from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuracao lida do ambiente e do `.env` na raiz do repositorio."""

    # `../.env` (raiz do repo, rodando de backend/) e `.env` (rodando da raiz); o ultimo vence.
    model_config = SettingsConfigDict(
        env_file=("../.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "postgresql+asyncpg://atendimento:atendimento@localhost:5432/atendimento"
    test_database_url: str = "postgresql+asyncpg://teste:teste@localhost:5433/teste"
    redis_url: str = "redis://localhost:6379/0"
    fila_janela_s: float = 10.0  # debounce: espera sem mensagem nova antes de processar
    fila_max_descartes: int = 2
    """Quantas respostas seguidas de uma conversa podem ser descartadas porque o cliente escreveu
    durante a geracao; passado o limite a resposta sai mesmo assim."""
    fila_trava_ttl_s: float = 120.0  # a trava de conversa expira se o worker morrer
    llm_provider: Literal["anthropic", "openai"] = "anthropic"
    """Quem atende a conversa. `openai` usa `OPENAI_API_KEY` e modelos `gpt-*` em `LLM_MODEL`."""
    llm_model: str = "claude-sonnet-5-5"
    llm_fallback_model: str = "claude-haiku-5-5"
    llm_effort: str = "low"
    anthropic_api_key: str | None = None
    llm_fake_latencia_ms: int | None = None
    """So para teste de carga: se definido, o LLM e simulado (texto fixo, sem custo) com essa
    latencia. `None` (padrao) = LLM real. Nunca ligar em producao."""
    llm_fake_jitter_ms: int = 0
    """Variacao (+/-) da latencia simulada, em ms."""
    openai_api_key: str | None = None
    """Chave da OpenAI (STT e TTS). Vazia = sem audio: pede texto e responde so em texto."""
    stt_model: str = "gpt-4o-mini-transcribe"
    tts_model: str = "gpt-4o-mini-tts"
    tts_voz: str = "cedar"
    midia_dir: str = "./.midias"
    """Pasta das midias enviadas pelo cliente (relativa ao cwd; ignorada pelo git)."""
    midia_max_bytes: int = 10 * 1024 * 1024
    api_publica_url: str = "http://localhost:8000"
    """Base publica da API: vira o prefixo das `midia_url` de midias que chegam pelo WhatsApp."""
    evolution_api_url: str = "http://localhost:8080"
    evolution_api_key: str = "troque-esta-chave"
    evolution_webhook_url: str = "http://host.docker.internal:8000/webhooks/evolution"
    """URL do webhook vista de dentro do container da Evolution (aponta para a nossa API)."""
    evolution_webhook_token: str = "troque-este-token"
    """Segredo compartilhado: a Evolution o envia em `X-Webhook-Token` (ou `?token=`)."""
    whatsapp_eco_graca_s: float = 0.5
    """Espera antes de tratar um `fromMe` desconhecido como do vendedor (corrida com o envio)."""
    painel_url: str = "http://localhost:3000"
    """Base do painel: vira o link `/conversas?lead=<id>` enviado ao vendedor no handoff."""
    mercadophone_mcp_url: str = "https://platform.mercadophone.tech/mcp/platform/"
    """Servidor MCP do Mercado Phone (ERP dos lojistas). Nao e segredo."""
    mercadophone_api_key: str | None = None
    """Chave da API do Mercado Phone (vai na query `key`; e segredo). Vazia = sem integracao."""
    sessao_ttl_horas: int = 168
    """Validade da sessao de login (renovada a cada uso) e do cookie."""
    cookie_secure: bool = False
    """Marca o cookie de sessao como `Secure` (exige HTTPS). Ligar em producao."""
    cors_origins: str = "http://localhost:3000"
    """Origens do painel (separadas por virgula) liberadas no CORS."""

    @property
    def origens_cors(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
