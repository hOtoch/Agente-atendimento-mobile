"""Fabrica do `LLMPort` a partir das settings."""

from __future__ import annotations

import anthropic

from app.adapters.outbound.llm.anthropic_adapter import AnthropicAdapter
from app.application.llm import (
    DefinicaoFerramenta,
    ErroLLM,
    LLMPort,
    MensagemLLM,
    RespostaLLM,
)
from app.infra.settings import Settings

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
