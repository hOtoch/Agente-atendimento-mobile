"""Cliente simulado: roteirizado (modo fake) ou LLM com persona (modo real)."""

from __future__ import annotations

from typing import Protocol

from app.application.llm import BlocoTexto, LLMPort, MensagemLLM, UsoTokens
from evals.modelos import Cenario, Evento, MensagemAgente, MensagemCliente

FIM = "[FIM]"

_SISTEMA = """\
Você está simulando um CLIENTE de uma loja de iPhones conversando por WhatsApp com o atendente \
virtual da loja. Você NÃO é o atendente. Escreva só a próxima fala do cliente, em português \
brasileiro informal, curta (uma ou duas frases), como uma pessoa real digitaria.

Persona: {persona}
Seu objetivo: {objetivo}
O que você sabe (responda apenas o que for perguntado; não entregue tudo de uma vez):
{sabe}

Regras:
- Fique no personagem. Não revele que é uma simulação.
- Se o atendente avisar que um vendedor humano vai continuar, ou se você já conseguiu o que \
queria (ou desistiu), responda exatamente {fim}.
- Responda somente com a fala do cliente (ou {fim}), sem aspas nem explicações.
"""


class Cliente(Protocol):
    uso: UsoTokens

    async def proxima_fala(self, eventos: list[Evento]) -> str | None:
        """Proxima fala do cliente, ou `None` para encerrar a conversa."""
        ...


class ClienteRoteirizado:
    def __init__(self, falas: tuple[str, ...]) -> None:
        self._falas = list(falas)
        self.uso = UsoTokens.vazio()

    async def proxima_fala(self, eventos: list[Evento]) -> str | None:
        return self._falas.pop(0) if self._falas else None


class ClienteLLM:
    """A abertura vem do roteiro (1a fala); as demais, do LLM com a persona do cenario."""

    def __init__(self, llm: LLMPort, cenario: Cenario) -> None:
        self._llm = llm
        self._abertura = cenario.roteiro[0]
        sabe = "\n".join(f"- {k}: {v}" for k, v in cenario.sabe.items()) or "- (nada em especial)"
        self._sistema = _SISTEMA.format(
            persona=cenario.persona, objetivo=cenario.objetivo, sabe=sabe, fim=FIM
        )
        self.uso = UsoTokens.vazio()

    async def proxima_fala(self, eventos: list[Evento]) -> str | None:
        if not any(isinstance(e, MensagemCliente) for e in eventos):
            return self._abertura
        mensagens = [MensagemLLM("user", [BlocoTexto("(a conversa com a loja começou)")])]
        for e in eventos:
            if isinstance(e, MensagemCliente):
                mensagens.append(MensagemLLM("assistant", [BlocoTexto(e.texto)]))
            elif isinstance(e, MensagemAgente):
                mensagens.append(MensagemLLM("user", [BlocoTexto(e.texto)]))
        resposta = await self._llm.responder([self._sistema], mensagens, [], max_tokens=200)
        self.uso = self.uso + resposta.uso
        texto = resposta.texto.strip()
        if not texto or FIM in texto:
            return None
        return texto
