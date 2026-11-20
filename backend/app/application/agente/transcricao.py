"""Transcricao do LLM: a conversa como o modelo a ve, gravada SO POR ACRESCIMO.

Cada `MensagemLLM` (user, assistant com `bruto`, tool_result e system de estado) e gravada em
ordem. O historico de um turno e a reproducao EXATA dela mais as mensagens novas: nada e
editado nem removido (preserved thinking exige os blocos de thinking intactos; e o prefixo
estavel mantem o cache de prompt valido).

O cursor `consumido_ate` marca ate onde as entradas do cliente ja viraram mensagens do LLM.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from app.application.llm import (
    Bloco,
    BlocoImagem,
    BlocoTexto,
    ChamadaFerramenta,
    MensagemLLM,
    Papel,
    ResultadoFerramenta,
)


@dataclass(frozen=True, slots=True)
class CursorEntrada:
    """Posicao da ultima entrada consumida: ordena por `(criado_em, id)`."""

    criado_em: datetime
    id: UUID


class RepositorioTranscricao(Protocol):
    async def listar(self, conversa_id: UUID) -> list[MensagemLLM]:
        """Todas as mensagens da conversa, na ordem em que foram gravadas."""
        ...

    async def acrescentar(
        self,
        conversa_id: UUID,
        mensagens: list[MensagemLLM],
        consumido_ate: CursorEntrada | None = None,
    ) -> None:
        """Grava as mensagens ao final; com `consumido_ate`, avanca o cursor atomicamente."""
        ...

    async def consumido_ate(self, conversa_id: UUID) -> CursorEntrada | None: ...

    async def marcar_consumidas(self, conversa_id: UUID, ate: CursorEntrada) -> None:
        """Avanca o cursor sem gravar mensagem (conversa com o vendedor)."""
        ...


# --- serializacao (JSON puro: vai no payload do evento `llm_mensagem`) -----------------------


def _serializar_bloco(bloco: Bloco) -> dict[str, Any]:
    if isinstance(bloco, BlocoTexto):
        return {"tipo": "texto", "texto": bloco.texto}
    if isinstance(bloco, BlocoImagem):
        return {
            "tipo": "imagem",
            "media_type": bloco.media_type,
            "dados_base64": bloco.dados_base64,
        }
    if isinstance(bloco, ChamadaFerramenta):
        return {
            "tipo": "chamada_ferramenta",
            "id": bloco.id,
            "nome": bloco.nome,
            "entrada": bloco.entrada,
        }
    return {
        "tipo": "resultado_ferramenta",
        "id_chamada": bloco.id_chamada,
        "conteudo": bloco.conteudo,
        "erro": bloco.erro,
    }


def _desserializar_bloco(dados: dict[str, Any]) -> Bloco:
    tipo = dados["tipo"]
    if tipo == "texto":
        return BlocoTexto(dados["texto"])
    if tipo == "imagem":
        return BlocoImagem(dados["media_type"], dados["dados_base64"])
    if tipo == "chamada_ferramenta":
        return ChamadaFerramenta(dados["id"], dados["nome"], dados["entrada"])
    if tipo == "resultado_ferramenta":
        return ResultadoFerramenta(dados["id_chamada"], dados["conteudo"], bool(dados["erro"]))
    raise ValueError(f"tipo de bloco desconhecido na transcricao: {tipo!r}")


def serializar_mensagem(msg: MensagemLLM) -> dict[str, Any]:
    return {
        "papel": msg.papel,
        "blocos": [_serializar_bloco(b) for b in msg.blocos],
        "bruto": msg.bruto,
    }


def desserializar_mensagem(dados: dict[str, Any]) -> MensagemLLM:
    papel: Papel = dados["papel"]
    return MensagemLLM(
        papel, [_desserializar_bloco(b) for b in dados["blocos"]], bruto=dados.get("bruto")
    )


# --- implementacao em memoria -----------------------------------------------------------------


class RepositorioTranscricaoEmMemoria:
    """Guarda as mensagens ja serializadas, para exercitar a ida e volta como o SQL."""

    def __init__(self) -> None:
        self._itens: defaultdict[UUID, list[dict[str, Any]]] = defaultdict(list)
        self._cursor: dict[UUID, CursorEntrada] = {}

    async def listar(self, conversa_id: UUID) -> list[MensagemLLM]:
        return [desserializar_mensagem(d) for d in self._itens.get(conversa_id, [])]

    async def acrescentar(
        self,
        conversa_id: UUID,
        mensagens: list[MensagemLLM],
        consumido_ate: CursorEntrada | None = None,
    ) -> None:
        self._itens[conversa_id].extend(serializar_mensagem(m) for m in mensagens)
        if consumido_ate is not None:
            self._cursor[conversa_id] = consumido_ate

    async def consumido_ate(self, conversa_id: UUID) -> CursorEntrada | None:
        return self._cursor.get(conversa_id)

    async def marcar_consumidas(self, conversa_id: UUID, ate: CursorEntrada) -> None:
        self._cursor[conversa_id] = ate
