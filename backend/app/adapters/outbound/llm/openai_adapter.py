"""Adaptador do `LLMPort` para a API Chat Completions da OpenAI, via httpx (sem SDK novo).

Traducao do formato neutro da porta:
- `sistema` vira mensagens `system` no topo, com o prefixo estavel primeiro: a OpenAI faz cache
  automatico de prefixos a partir de 1024 tokens (sem marcacao e sem custo de escrita).
- `MensagemLLM("system")` no meio da conversa vira `{"role": "system"}`.
- `ChamadaFerramenta` vira `tool_calls` do assistant (argumentos em JSON string) e cada
  `ResultadoFerramenta` vira uma mensagem `{"role": "tool"}` logo depois do assistant, como a API
  exige; texto/imagem do mesmo turno do usuario vao numa mensagem `user` em seguida.
- `bruto` (content original de respostas da Anthropic) e ignorado: os `blocos` bastam aqui.
- Ferramentas sem `strict`: o modo estrito da OpenAI exige todo parametro em `required`, e os
  esquemas do projeto tem opcionais; a validacao de argumentos continua no codigo das ferramentas.
- `motivo_parada` usa o vocabulario do projeto (`end_turn`, `tool_use`, `max_tokens`).
- `reasoning_effort` so vai para modelos de raciocinio (`gpt-5*`, `o*`).
- O modelo reportado (uso e `modelo_usado`) e o configurado, sem a data do snapshot que a API
  devolve, para a tabela de precos e a telemetria acharem o modelo.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import httpx

from app.application.llm import (
    Bloco,
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

_ROTA = "/v1/chat/completions"
_STATUS_TRANSITORIOS = frozenset({408, 409, 429}) | frozenset(range(500, 600))
_PREFIXOS_RACIOCINIO = ("gpt-5", "o1", "o3", "o4")
_MOTIVOS = {"stop": "end_turn", "tool_calls": "tool_use", "length": "max_tokens"}

# Os modelos da OpenAI tendem a responder so em texto e a seguir a "PROXIMA PERGUNTA" do estado,
# que e montada antes de o modelo ler a fala do cliente. Texto fixo (cacheavel), so deste provedor.
INSTRUCAO_FERRAMENTAS = (
    "COMO USAR AS FERRAMENTAS (obrigatório): a cada mensagem do cliente, ANTES de escrever a "
    "resposta, registre com a ferramenta certa tudo o que ele acabou de informar (aparelho, "
    "capacidade, cor, item escolhido, troca e estado do usado, data da compra, pagamento) e "
    "consulte o estoque quando souber o modelo. A PRÓXIMA PERGUNTA do estado do atendimento foi "
    "calculada antes da mensagem do cliente: se ele já respondeu, registre e siga para a "
    "pendência seguinte, sem perguntar de novo. Valores em reais só saem de calcular_proposta. "
    "Uma pergunta por mensagem."
)


def criar_cliente_http(*, timeout_s: float = 30.0) -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url="https://api.openai.com", timeout=timeout_s)


class _Transitorio(Exception):
    def __init__(self, status: int | None, detalhe: str) -> None:
        super().__init__(detalhe)
        self.status = status


def _conteudo_usuario(bloco: Bloco) -> dict[str, Any]:
    if isinstance(bloco, BlocoTexto):
        return {"type": "text", "text": bloco.texto}
    if isinstance(bloco, BlocoImagem):
        url = f"data:{bloco.media_type};base64,{bloco.dados_base64}"
        return {"type": "image_url", "image_url": {"url": url}}
    raise TypeError(f"bloco invalido numa mensagem do usuario: {bloco!r}")


def _mensagens_para_api(m: MensagemLLM) -> list[dict[str, Any]]:
    if m.papel == "system":
        textos = [b.texto for b in m.blocos if isinstance(b, BlocoTexto)]
        return [{"role": "system", "content": "\n\n".join(textos)}]
    if m.papel == "assistant":
        texto = "".join(b.texto for b in m.blocos if isinstance(b, BlocoTexto))
        chamadas = [b for b in m.blocos if isinstance(b, ChamadaFerramenta)]
        msg: dict[str, Any] = {"role": "assistant", "content": texto or None}
        if chamadas:
            msg["tool_calls"] = [
                {
                    "id": c.id,
                    "type": "function",
                    "function": {"name": c.nome, "arguments": json.dumps(c.entrada)},
                }
                for c in chamadas
            ]
        return [msg]
    saida: list[dict[str, Any]] = [
        {
            "role": "tool",
            "tool_call_id": b.id_chamada,
            "content": f"ERRO: {b.conteudo}" if b.erro else b.conteudo,
        }
        for b in m.blocos
        if isinstance(b, ResultadoFerramenta)
    ]
    resto = [_conteudo_usuario(b) for b in m.blocos if not isinstance(b, ResultadoFerramenta)]
    if resto:
        saida.append({"role": "user", "content": resto})
    return saida


def _ferramenta_para_api(f: DefinicaoFerramenta) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {"name": f.nome, "description": f.descricao, "parameters": f.esquema_json},
    }


def _argumentos(bruto: Any) -> dict[str, Any]:
    try:
        valor = json.loads(bruto) if isinstance(bruto, str) else bruto
    except ValueError:
        return {}
    return valor if isinstance(valor, dict) else {}


def _fala_do_cliente_por_ultimo(mensagens: list[MensagemLLM]) -> list[MensagemLLM]:
    """Poe a mensagem `system` que segue uma fala do cliente ANTES dela.

    O orquestrador grava `[usuario, estado]` a cada turno, e o estado e montado antes de o modelo
    ler a fala. Com o estado por ultimo, os modelos da OpenAI seguem a "proxima pergunta" dele e
    ignoram o que o cliente acabou de dizer. Uma fala com resultados de ferramenta nao se move:
    eles precisam vir logo depois das chamadas do assistant. A troca e deterministica, entao o
    prefixo cacheado do historico nao muda de um turno para o outro.
    """
    saida = list(mensagens)
    for i in range(len(saida) - 1):
        atual, seguinte = saida[i], saida[i + 1]
        if (
            atual.papel == "user"
            and seguinte.papel == "system"
            and not any(isinstance(b, ResultadoFerramenta) for b in atual.blocos)
        ):
            saida[i], saida[i + 1] = seguinte, atual
    return saida


def _detalhe_erro(resposta: httpx.Response) -> str:
    try:
        return str(resposta.json()["error"]["message"])
    except (ValueError, KeyError, TypeError):
        return resposta.text[:200]


class OpenAIAdapter:
    """`tentativas` = total de chamadas por modelo (1 + retries); o reserva tem as mesmas."""

    def __init__(
        self,
        cliente: httpx.AsyncClient,
        *,
        api_key: str,
        modelo: str,
        modelo_reserva: str | None,
        effort: str = "low",
        tentativas: int = 2,
        backoff_s: float = 0.5,
    ) -> None:
        if tentativas < 1:
            raise ValueError("tentativas deve ser >= 1")
        self._cliente = cliente
        self._api_key = api_key
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
        mensagens_api: list[dict[str, Any]] = [{"role": "system", "content": t} for t in sistema]
        mensagens_api.append({"role": "system", "content": INSTRUCAO_FERRAMENTAS})
        for m in _fala_do_cliente_por_ultimo(mensagens):
            mensagens_api.extend(_mensagens_para_api(m))
        base: dict[str, Any] = {"messages": mensagens_api, "max_completion_tokens": max_tokens}
        if ferramentas:
            base["tools"] = [_ferramenta_para_api(f) for f in ferramentas]

        modelos = [self.modelo]
        if self.modelo_reserva and self.modelo_reserva != self.modelo:
            modelos.append(self.modelo_reserva)

        ultimo_erro: _Transitorio | None = None
        for modelo in modelos:
            for tentativa in range(self._tentativas):
                try:
                    corpo = await self._chamar(modelo, base)
                except _Transitorio as e:
                    ultimo_erro = e
                    logger.warning(
                        "LLM transitorio modelo=%s tentativa=%d/%d status=%s",
                        modelo,
                        tentativa + 1,
                        self._tentativas,
                        e.status,
                    )
                    if tentativa + 1 < self._tentativas and self._backoff_s > 0:
                        await asyncio.sleep(self._backoff_s * (2**tentativa))
                else:
                    return self._converter(corpo, modelo)
        raise LLMIndisponivel(
            f"LLM indisponivel apos tentar {modelos}: {ultimo_erro}",
            status=ultimo_erro.status if ultimo_erro else None,
            modelo=modelos[-1],
        ) from ultimo_erro

    async def _chamar(self, modelo: str, base: dict[str, Any]) -> dict[str, Any]:
        corpo = {"model": modelo, **base}
        if modelo.startswith(_PREFIXOS_RACIOCINIO):
            corpo["reasoning_effort"] = self._effort
        try:
            resposta = await self._cliente.post(
                _ROTA, headers={"Authorization": f"Bearer {self._api_key}"}, json=corpo
            )
        except httpx.TransportError as e:
            raise _Transitorio(None, type(e).__name__) from e
        if resposta.status_code in _STATUS_TRANSITORIOS:
            raise _Transitorio(resposta.status_code, _detalhe_erro(resposta))
        if resposta.status_code != 200:
            raise ErroLLM(
                f"erro da API OpenAI ({resposta.status_code}): {_detalhe_erro(resposta)}",
                status=resposta.status_code,
                modelo=modelo,
            )
        try:
            dados = resposta.json()
        except ValueError as e:
            raise ErroLLM("resposta inesperada da OpenAI (nao e JSON)", modelo=modelo) from e
        if not isinstance(dados, dict):
            raise ErroLLM("resposta inesperada da OpenAI", modelo=modelo)
        return dados

    def _converter(self, corpo: dict[str, Any], modelo: str) -> RespostaLLM:
        try:
            escolha = corpo["choices"][0]
            mensagem = escolha["message"]
            motivo = escolha.get("finish_reason") or ""
            uso_api = corpo.get("usage") or {}
        except (KeyError, IndexError, TypeError) as e:
            raise ErroLLM("resposta inesperada da OpenAI", modelo=modelo) from e

        if mensagem.get("refusal") or motivo == "content_filter":
            logger.warning("LLM recusou modelo=%s motivo=%s", modelo, motivo)
            raise LLMRecusou(motivo or "refusal", mensagem.get("refusal"), modelo=modelo)

        texto = mensagem.get("content") or ""
        chamadas = [
            ChamadaFerramenta(
                c["id"], c["function"]["name"], _argumentos(c["function"].get("arguments"))
            )
            for c in mensagem.get("tool_calls") or []
        ]
        blocos: list[Bloco] = [BlocoTexto(texto)] if texto else []
        blocos.extend(chamadas)

        cache = int((uso_api.get("prompt_tokens_details") or {}).get("cached_tokens") or 0)
        uso = UsoTokens(
            modelo=modelo,
            entrada=int(uso_api.get("prompt_tokens") or 0) - cache,
            saida=int(uso_api.get("completion_tokens") or 0),
            cache_leitura=cache,
            cache_escrita=0,
        )
        logger.info(
            "LLM uso modelo=%s entrada=%d saida=%d cache_leitura=%d parada=%s",
            uso.modelo,
            uso.entrada,
            uso.saida,
            uso.cache_leitura,
            motivo,
        )
        return RespostaLLM(
            texto=texto,
            chamadas=chamadas,
            mensagem_assistente=MensagemLLM("assistant", blocos),
            uso=uso,
            motivo_parada=_MOTIVOS.get(motivo, motivo),
            modelo_usado=modelo,
        )
