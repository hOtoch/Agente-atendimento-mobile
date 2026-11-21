"""`criar_llm`: o LLM simulado (carga) so liga por configuracao explicita, nunca por padrao."""

from __future__ import annotations

from app.adapters.outbound.llm.anthropic_adapter import AnthropicAdapter
from app.adapters.outbound.llm.simulado import LLMSimulado
from app.infra.llm import _LLMSemChave, criar_llm
from app.infra.settings import Settings


def _settings(**campos: object) -> Settings:
    return Settings(_env_file=None, **campos)  # type: ignore[call-arg]


def test_por_padrao_o_llm_simulado_esta_desligado() -> None:
    settings = _settings()
    assert settings.llm_fake_latencia_ms is None
    assert isinstance(criar_llm(settings), _LLMSemChave)


def test_com_chave_e_sem_simulacao_usa_o_adaptador_real() -> None:
    assert isinstance(criar_llm(_settings(anthropic_api_key="sk-teste")), AnthropicAdapter)


def test_latencia_configurada_liga_o_simulado_mesmo_sem_chave() -> None:
    llm = criar_llm(_settings(llm_fake_latencia_ms=2750, llm_fake_jitter_ms=1250))
    assert isinstance(llm, LLMSimulado)


def test_simulado_tem_precedencia_sobre_a_chave_real() -> None:
    """Garantia anti-custo: com a simulacao ligada nunca se fala com a Anthropic."""
    llm = criar_llm(_settings(llm_fake_latencia_ms=0, anthropic_api_key="sk-teste"))
    assert isinstance(llm, LLMSimulado)
