"""`criar_llm`: o LLM simulado (carga) so liga por configuracao explicita, nunca por padrao."""

from __future__ import annotations

import logging

import pytest

from app.adapters.outbound.llm.anthropic_adapter import AnthropicAdapter
from app.adapters.outbound.llm.openai_adapter import OpenAIAdapter
from app.adapters.outbound.llm.simulado import LLMSimulado
from app.application.llm import BlocoTexto, ErroLLM, MensagemLLM
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


def test_provedor_padrao_e_a_anthropic() -> None:
    assert _settings().llm_provider == "anthropic"


def test_provedor_openai_com_chave_usa_o_adaptador_da_openai() -> None:
    llm = criar_llm(
        _settings(
            llm_provider="openai",
            openai_api_key="sk-teste",
            llm_model="gpt-4.1-mini",
            llm_fallback_model="gpt-4o-mini",
        )
    )
    assert isinstance(llm, OpenAIAdapter)
    assert (llm.modelo, llm.modelo_reserva) == ("gpt-4.1-mini", "gpt-4o-mini")


def test_provedor_openai_ignora_a_chave_da_anthropic() -> None:
    llm = criar_llm(_settings(llm_provider="openai", anthropic_api_key="sk-ant"))
    assert isinstance(llm, _LLMSemChave)


async def test_provedor_openai_sem_chave_aponta_a_variavel_certa() -> None:
    llm = criar_llm(_settings(llm_provider="openai"))
    with pytest.raises(ErroLLM, match="OPENAI_API_KEY"):
        await llm.responder(["s"], [MensagemLLM("user", [BlocoTexto("oi")])], [])


def test_provedor_openai_ignora_reserva_igual_ao_principal() -> None:
    llm = criar_llm(
        _settings(
            llm_provider="openai",
            openai_api_key="k",
            llm_model="gpt-4.1-mini",
            llm_fallback_model="gpt-4.1-mini",
        )
    )
    assert isinstance(llm, OpenAIAdapter)
    assert llm.modelo_reserva is None


def test_provedor_desconhecido_e_recusado() -> None:
    with pytest.raises(ValueError, match="llm_provider"):
        _settings(llm_provider="gemini")


def test_simulado_ligado_avisa_no_log(caplog: pytest.LogCaptureFixture) -> None:
    """Se `LLM_FAKE_LATENCIA_MS` vazar para producao, o log diz que o agente nao e real."""
    with caplog.at_level(logging.WARNING, logger="app.infra.llm"):
        criar_llm(_settings(llm_fake_latencia_ms=0))
    assert "LLM_FAKE_LATENCIA_MS" in caplog.text
