"""FakeLLM: roteiro de respostas para os testes do projeto inteiro (nunca toca a rede)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from app.application.llm import (
    Bloco,
    BlocoTexto,
    ChamadaFerramenta,
    DefinicaoFerramenta,
    ErroLLM,
    MensagemLLM,
    RespostaLLM,
    UsoTokens,
)


class RoteiroEsgotado(ErroLLM):
    """O teste pediu mais respostas do que o roteiro tinha."""


@dataclass(slots=True)
class RespostaRoteirizada:
    """Uma resposta do roteiro. `erro` (se houver) e levantado no lugar de responder."""

    texto: str = ""
    chamadas: list[ChamadaFerramenta] = field(default_factory=list)
    uso: UsoTokens | None = None
    motivo_parada: str | None = None
    modelo: str = "fake"
    erro: ErroLLM | None = None


@dataclass(frozen=True, slots=True)
class ChamadaRecebida:
    sistema: list[str]
    mensagens: list[MensagemLLM]
    ferramentas: list[DefinicaoFerramenta]
    max_tokens: int


Roteiro = RespostaRoteirizada | Callable[[list[MensagemLLM]], RespostaRoteirizada]


class FakeLLM:
    """Implementa `LLMPort`: devolve as respostas do roteiro na ordem e registra o que recebeu."""

    def __init__(self, roteiro: list[Roteiro]) -> None:
        self._roteiro = list(roteiro)
        self.chamadas: list[ChamadaRecebida] = []
        self.uso_total: UsoTokens = UsoTokens.vazio()

    async def responder(
        self,
        sistema: list[str],
        mensagens: list[MensagemLLM],
        ferramentas: list[DefinicaoFerramenta],
        max_tokens: int = 1024,
    ) -> RespostaLLM:
        self.chamadas.append(
            ChamadaRecebida(list(sistema), list(mensagens), list(ferramentas), max_tokens)
        )
        numero = len(self.chamadas)
        if numero > len(self._roteiro):
            raise RoteiroEsgotado(
                f"roteiro do FakeLLM esgotado: chamada {numero}, "
                f"mas so ha {len(self._roteiro)} resposta(s)"
            )
        item = self._roteiro[numero - 1]
        resposta = item(list(mensagens)) if callable(item) else item
        if resposta.erro is not None:
            raise resposta.erro

        blocos: list[Bloco] = []
        if resposta.texto:
            blocos.append(BlocoTexto(resposta.texto))
        blocos.extend(resposta.chamadas)
        uso = resposta.uso or UsoTokens.vazio(resposta.modelo)
        self.uso_total = self.uso_total + uso
        return RespostaLLM(
            texto=resposta.texto,
            chamadas=list(resposta.chamadas),
            mensagem_assistente=MensagemLLM("assistant", blocos),
            uso=uso,
            motivo_parada=resposta.motivo_parada
            or ("tool_use" if resposta.chamadas else "end_turn"),
            modelo_usado=resposta.modelo,
        )
