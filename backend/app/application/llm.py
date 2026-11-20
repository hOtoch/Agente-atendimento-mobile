"""Porta do LLM: tipos neutros de provedor (sem SDK) e o `LLMPort`.

`responder` faz UM request logico. O loop de ferramentas (executar `chamadas`, devolver
`ResultadoFerramenta` e chamar de novo) fica no orquestrador da conversa.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Protocol

Papel = Literal["user", "assistant", "system"]
_PAPEIS = ("user", "assistant", "system")


@dataclass(frozen=True, slots=True)
class BlocoTexto:
    texto: str


@dataclass(frozen=True, slots=True)
class BlocoImagem:
    media_type: str
    dados_base64: str


@dataclass(frozen=True, slots=True)
class ChamadaFerramenta:
    """Pedido do modelo para executar uma ferramenta."""

    id: str
    nome: str
    entrada: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ResultadoFerramenta:
    """Resposta do codigo a uma `ChamadaFerramenta` (vai numa mensagem `user`)."""

    id_chamada: str
    conteudo: str
    erro: bool = False


Bloco = BlocoTexto | BlocoImagem | ChamadaFerramenta | ResultadoFerramenta


@dataclass(frozen=True, slots=True)
class MensagemLLM:
    """Mensagem da conversa.

    `papel="system"` e uma instrucao no meio da conversa (so texto), ex.: o estado da ficha.
    `bruto` guarda o `content` original de uma resposta do assistant (thinking, assinaturas,
    ...); quando existe, o adaptador o reenvia no lugar de `blocos`.
    """

    papel: Papel
    blocos: list[Bloco]
    bruto: list[dict[str, Any]] | None = None

    def __post_init__(self) -> None:
        if self.papel not in _PAPEIS:
            raise ValueError(f"papel invalido: {self.papel!r}")
        if self.papel == "system" and not all(isinstance(b, BlocoTexto) for b in self.blocos):
            raise ValueError("mensagem de sistema aceita apenas blocos de texto")


@dataclass(frozen=True, slots=True)
class DefinicaoFerramenta:
    """Ferramenta oferecida ao modelo. `estrita` = argumentos sempre validos pelo esquema
    (o esquema precisa ter `required` e `additionalProperties: false`)."""

    nome: str
    descricao: str
    esquema_json: dict[str, Any]
    estrita: bool = True


@dataclass(frozen=True, slots=True)
class UsoTokens:
    """Consumo de uma ou mais chamadas. `entrada` e so a parte nao cacheada do prompt."""

    modelo: str
    entrada: int
    saida: int
    cache_leitura: int
    cache_escrita: int

    @classmethod
    def vazio(cls, modelo: str = "") -> UsoTokens:
        return cls(modelo, 0, 0, 0, 0)

    def __add__(self, outro: object) -> UsoTokens:
        if not isinstance(outro, UsoTokens):
            return NotImplemented
        if not self.modelo:
            modelo = outro.modelo
        elif not outro.modelo or outro.modelo == self.modelo:
            modelo = self.modelo
        else:
            modelo = "misto"
        return UsoTokens(
            modelo,
            self.entrada + outro.entrada,
            self.saida + outro.saida,
            self.cache_leitura + outro.cache_leitura,
            self.cache_escrita + outro.cache_escrita,
        )

    def __radd__(self, outro: object) -> UsoTokens:
        if outro == 0:  # ponto de partida do `sum()`
            return self
        return NotImplemented


@dataclass(frozen=True, slots=True)
class RespostaLLM:
    texto: str
    chamadas: list[ChamadaFerramenta]
    mensagem_assistente: MensagemLLM
    uso: UsoTokens
    motivo_parada: str
    modelo_usado: str


class ErroLLM(Exception):
    """Falha ao falar com o LLM."""


class LLMIndisponivel(ErroLLM):
    """Rede, 429 ou 5xx esgotados (inclusive no modelo reserva)."""


class LLMRecusou(ErroLLM):
    """O modelo recusou a requisicao (recusa final, depois de qualquer fallback)."""

    def __init__(self, categoria: str | None, mensagem: str | None = None) -> None:
        super().__init__(mensagem or f"LLM recusou a requisicao (categoria={categoria})")
        self.categoria = categoria


class LLMPort(Protocol):
    async def responder(
        self,
        sistema: list[str],
        mensagens: list[MensagemLLM],
        ferramentas: list[DefinicaoFerramenta],
        max_tokens: int = 1024,
    ) -> RespostaLLM:
        """Um request ao modelo.

        `sistema[0]` e o prefixo estavel e cacheavel; os demais vem depois do breakpoint de
        cache. Levanta `LLMIndisponivel`, `LLMRecusou` ou `ErroLLM`.
        """
        ...
