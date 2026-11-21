"""LLM simulado para teste de carga: texto fixo apos uma latencia realista (nunca toca a rede).

Ligado so por `LLM_FAKE_LATENCIA_MS` (ver `app.infra.llm.criar_llm`); fica desligado por padrao.
"""

from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable

from app.application.llm import (
    BlocoTexto,
    DefinicaoFerramenta,
    MensagemLLM,
    RespostaLLM,
    UsoTokens,
)

TEXTO_SIMULADO = "Claro! Ja separei essas informacoes para voce. Posso te ajudar com mais alguma?"


class LLMSimulado:
    """Implementa `LLMPort`: responde `TEXTO_SIMULADO` depois de `latencia_ms` +/- `jitter_ms`."""

    def __init__(
        self,
        *,
        latencia_ms: int = 0,
        jitter_ms: int = 0,
        dormir: Callable[[float], Awaitable[None]] = asyncio.sleep,
        aleatorio: random.Random | None = None,
    ) -> None:
        if latencia_ms < 0 or jitter_ms < 0:
            raise ValueError("latencia_ms e jitter_ms nao podem ser negativos")
        self._latencia_ms = latencia_ms
        self._jitter_ms = jitter_ms
        self._dormir = dormir
        self._aleatorio = aleatorio or random.Random()

    async def responder(
        self,
        sistema: list[str],
        mensagens: list[MensagemLLM],
        ferramentas: list[DefinicaoFerramenta],
        max_tokens: int = 1024,
    ) -> RespostaLLM:
        desvio = self._aleatorio.uniform(-self._jitter_ms, self._jitter_ms)
        await self._dormir(max(self._latencia_ms + desvio, 0.0) / 1000)
        return RespostaLLM(
            texto=TEXTO_SIMULADO,
            chamadas=[],
            mensagem_assistente=MensagemLLM("assistant", [BlocoTexto(TEXTO_SIMULADO)]),
            uso=UsoTokens.vazio("simulado"),
            motivo_parada="end_turn",
            modelo_usado="simulado",
        )
