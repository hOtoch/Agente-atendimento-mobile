"""Fabrica do `LLMPort` a partir das settings."""

from __future__ import annotations

import logging

import anthropic

from app.adapters.outbound.llm.anthropic_adapter import AnthropicAdapter
from app.adapters.outbound.llm.simulado import LLMSimulado
from app.application.llm import (
    DefinicaoFerramenta,
    ErroLLM,
    LLMPort,
    MensagemLLM,
    RespostaLLM,
)
from app.infra.settings import Settings

logger = logging.getLogger(__name__)

_TIMEOUT_S = 30.0


class LLMNaoConfigurado(ErroLLM):
    """`ANTHROPIC_API_KEY` ausente: so aparece quando o LLM e usado."""


class _LLMSemChave:
    async def responder(
        self,
        sistema: list[str],
        mensagens: list[MensagemLLM],
        ferramentas: list[DefinicaoFerramenta],
        max_tokens: int = 1024,
    ) -> RespostaLLM:
        raise LLMNaoConfigurado(
            "ANTHROPIC_API_KEY nao configurada: defina a chave no .env para usar o LLM real "
            "(testes usam FakeLLM)"
        )


def criar_llm(settings: Settings) -> LLMPort:
    if settings.llm_fake_latencia_ms is not None:
        # Teste de carga: tem precedencia sobre a chave para nunca gerar custo.
        logger.warning(
            "LLM_FAKE_LATENCIA_MS=%s: LLM SIMULADO ligado (so para teste de carga), o agente "
            "responde texto fixo",
            settings.llm_fake_latencia_ms,
        )
        return LLMSimulado(
            latencia_ms=settings.llm_fake_latencia_ms, jitter_ms=settings.llm_fake_jitter_ms
        )
    if not settings.anthropic_api_key:
        return _LLMSemChave()
    # max_retries=0: quem faz retry e fallback de modelo e o adaptador (evita retries multiplicados)
    cliente = anthropic.AsyncAnthropic(
        api_key=settings.anthropic_api_key, max_retries=0, timeout=_TIMEOUT_S
    )
    reserva = settings.llm_fallback_model or None
    if reserva == settings.llm_model:
        reserva = None
    return AnthropicAdapter(cliente, settings.llm_model, reserva, effort=settings.llm_effort)
