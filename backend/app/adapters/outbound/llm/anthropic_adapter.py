"""Adaptador do `LLMPort` para a API da Anthropic (SDK oficial).

Formato usado (ver docs do SDK):
- `output_config={"effort": ...}`; `thinking` omitido (adaptativo); sem `temperature`/`top_p`/
  `top_k`, sem `tool_choice` forcado, sem prefill.
- `cache_control={"type": "ephemeral"}` na ultima ferramenta e no `sistema[0]` (prefixo estavel),
  e no ultimo bloco da ultima mensagem do usuario (cache incremental: o historico e so de
  acrescimo, entao o turno seguinte le a conversa do cache).
- Sonnet 5.5: `client.beta.messages.create(betas=["server-side-fallback-2026-07-01"],
  fallbacks="default")` para recusas. Haiku 5.5 nao tem fallback de recusa.
- Mensagens `system` no meio da conversa vao como `{"role": "system", "content": "<texto>"}`.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import anthropic

from app.application.llm import (
    BlocoImagem,
    BlocoTexto,
    ChamadaFerramenta,
    DefinicaoFerramenta,
    ErroLLM,
    LLMIndisponivel,
    LLMRecusou,
    MensagemLLM,
    RespostaLLM,
    ResultadoFerramenta,
    UsoTokens,
)

logger = logging.getLogger(__name__)

BETA_FALLBACK = "server-side-fallback-2026-07-01"
_MODELOS_COM_FALLBACK = ("claude-sonnet-5-5",)
_EPHEMERAL = {"type": "ephemeral"}
_TRANSITORIOS = (
    anthropic.RateLimitError,
    anthropic.InternalServerError,  # 5xx, inclusive 529 (overloaded)
    anthropic.APIConnectionError,  # inclui APITimeoutError
)
_ANTES_DO_FALLBACK = ("thinking", "redacted_thinking", "tool_use")


def _bloco_para_api(bloco: Any) -> dict[str, Any]:
    if isinstance(bloco, BlocoTexto):
        return {"type": "text", "text": bloco.texto}
    if isinstance(bloco, BlocoImagem):
        return {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": bloco.media_type,
                "data": bloco.dados_base64,
            },
        }
    if isinstance(bloco, ChamadaFerramenta):
        return {"type": "tool_use", "id": bloco.id, "name": bloco.nome, "input": bloco.entrada}
    if isinstance(bloco, ResultadoFerramenta):
        resultado: dict[str, Any] = {
            "type": "tool_result",
            "tool_use_id": bloco.id_chamada,
            "content": bloco.conteudo,
        }
        if bloco.erro:
            resultado["is_error"] = True
        return resultado
    raise TypeError(f"bloco desconhecido: {bloco!r}")


def _reenviar_bruto(bruto: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Devolve o content do assistant como veio. Unica excecao documentada: apos um bloco
    `fallback`, thinking/tool_use anteriores a ele sao omitidos e o proprio bloco fica."""
    ultimo = max((i for i, b in enumerate(bruto) if b.get("type") == "fallback"), default=-1)
    if ultimo < 0:
        return bruto
    return [b for i, b in enumerate(bruto) if i > ultimo or b.get("type") not in _ANTES_DO_FALLBACK]


def _mensagem_para_api(m: MensagemLLM) -> dict[str, Any]:
    if m.papel == "system":
        textos = [b.texto for b in m.blocos if isinstance(b, BlocoTexto)]
        return {"role": "system", "content": "\n\n".join(textos)}
    if m.papel == "assistant" and m.bruto is not None:
        return {"role": "assistant", "content": _reenviar_bruto(m.bruto)}
    blocos = [
        _bloco_para_api(b)
        for b in m.blocos
        if not (isinstance(b, BlocoTexto) and not b.texto and m.papel == "assistant")
    ]
    return {"role": m.papel, "content": blocos}


def _marcar_cache_incremental(mensagens: list[dict[str, Any]]) -> None:
    """Breakpoint no ultimo bloco da ultima mensagem `user` (copia o bloco; nao muta o bruto)."""
    for m in reversed(mensagens):
        if m["role"] == "user" and isinstance(m["content"], list) and m["content"]:
            m["content"] = [
                *m["content"][:-1],
                {**m["content"][-1], "cache_control": dict(_EPHEMERAL)},
            ]
            return


def _ferramenta_para_api(f: DefinicaoFerramenta) -> dict[str, Any]:
    t: dict[str, Any] = {"name": f.nome, "description": f.descricao, "input_schema": f.esquema_json}
    if f.estrita:
        t["strict"] = True
    return t


class AnthropicAdapter:
    """`tentativas` = total de chamadas por modelo (1 + retries); o reserva tem as mesmas."""

    def __init__(
        self,
        cliente: anthropic.AsyncAnthropic,
        modelo: str,
        modelo_reserva: str | None,
        effort: str = "low",
        tentativas: int = 2,
        backoff_s: float = 0.5,
    ) -> None:
        if tentativas < 1:
            raise ValueError("tentativas deve ser >= 1")
        self._cliente = cliente
        self.modelo = modelo
        self.modelo_reserva = modelo_reserva
        self._effort = effort
        self._tentativas = tentativas
        self._backoff_s = backoff_s

    async def responder(
        self,
        sistema: list[str],
        mensagens: list[MensagemLLM],
        ferramentas: list[DefinicaoFerramenta],
        max_tokens: int = 1024,
    ) -> RespostaLLM:
        mensagens_api = [_mensagem_para_api(m) for m in mensagens]
        _marcar_cache_incremental(mensagens_api)
        base: dict[str, Any] = {
            "max_tokens": max_tokens,
            "messages": mensagens_api,
            "output_config": {"effort": self._effort},
        }
        if sistema:
            blocos: list[dict[str, Any]] = [{"type": "text", "text": t} for t in sistema]
            blocos[0]["cache_control"] = dict(_EPHEMERAL)
            base["system"] = blocos
        if ferramentas:
            tools = [_ferramenta_para_api(f) for f in ferramentas]
            tools[-1]["cache_control"] = dict(_EPHEMERAL)
            base["tools"] = tools

        modelos = [self.modelo]
        if self.modelo_reserva and self.modelo_reserva != self.modelo:
            modelos.append(self.modelo_reserva)

        ultimo_erro: Exception | None = None
        for modelo in modelos:
            for tentativa in range(self._tentativas):
                try:
                    resposta = await self._chamar(modelo, base)
                except _TRANSITORIOS as e:
                    ultimo_erro = e
                    logger.warning(
                        "LLM transitorio modelo=%s tentativa=%d/%d erro=%s",
                        modelo,
                        tentativa + 1,
                        self._tentativas,
                        type(e).__name__,
                    )
                    if tentativa + 1 < self._tentativas and self._backoff_s > 0:
                        await asyncio.sleep(self._backoff_s * (2**tentativa))
                except anthropic.APIStatusError as e:
                    raise ErroLLM(f"erro da API Anthropic ({e.status_code}): {e.message}") from e
                else:
                    return self._converter(resposta)
        raise LLMIndisponivel(
            f"LLM indisponivel apos tentar {modelos}: {ultimo_erro}"
        ) from ultimo_erro

    async def _chamar(self, modelo: str, base: dict[str, Any]) -> Any:
        if modelo in _MODELOS_COM_FALLBACK:
            return await self._cliente.beta.messages.create(
                model=modelo, betas=[BETA_FALLBACK], fallbacks="default", **base
            )
        return await self._cliente.messages.create(model=modelo, **base)

    def _converter(self, r: Any) -> RespostaLLM:
        if r.stop_reason == "refusal":
            detalhes = getattr(r, "stop_details", None)
            categoria = getattr(detalhes, "category", None)
            logger.warning("LLM recusou modelo=%s categoria=%s", r.model, categoria)
            raise LLMRecusou(categoria)

        texto = "".join(b.text for b in r.content if b.type == "text")
        chamadas = [
            ChamadaFerramenta(b.id, b.name, dict(b.input))
            for b in r.content
            if b.type == "tool_use"
        ]
        blocos: list[Any] = [BlocoTexto(b.text) for b in r.content if b.type == "text" and b.text]
        blocos.extend(chamadas)
        bruto = [b.model_dump(mode="json", by_alias=True, exclude_none=True) for b in r.content]
        u = r.usage
        uso = UsoTokens(
            modelo=r.model,
            entrada=u.input_tokens,
            saida=u.output_tokens,
            cache_leitura=u.cache_read_input_tokens or 0,
            cache_escrita=u.cache_creation_input_tokens or 0,
        )
        logger.info(
            "LLM uso modelo=%s entrada=%d saida=%d cache_leitura=%d cache_escrita=%d parada=%s",
            uso.modelo,
            uso.entrada,
            uso.saida,
            uso.cache_leitura,
            uso.cache_escrita,
            r.stop_reason,
        )
        return RespostaLLM(
            texto=texto,
            chamadas=chamadas,
            mensagem_assistente=MensagemLLM("assistant", blocos, bruto=bruto),
            uso=uso,
            motivo_parada=r.stop_reason or "",
            modelo_usado=r.model,
        )
