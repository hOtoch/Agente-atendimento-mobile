"""Normaliza o payload do webhook `instagram` da Graph API em `MensagemEntrada`.

Funcao pura: nunca estoura. O que nao interessa (eco da propria conta, reacao, leitura, postback,
mensagem apagada, anexo que nao tratamos, conta de outra loja) volta como `Ignorado` com o motivo,
e o webhook responde 200 para a Meta nao reenviar.

Um envelope pode trazer varias mensagens (`entry[].messaging[]`), por isso o resultado e uma lista.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from app.application.canal import Canal, MensagemEntrada, TipoMensagem

_ANEXOS = {"image": TipoMensagem.IMAGEM, "audio": TipoMensagem.AUDIO}


@dataclass(frozen=True, slots=True)
class Ignorado:
    motivo: str


Resultado = MensagemEntrada | Ignorado


def normalizar(payload: object, *, loja_da_conta: Callable[[str], UUID | None]) -> list[Resultado]:
    """`loja_da_conta` traduz o id da conta profissional (`entry[].id`) na loja dona dela."""
    if not isinstance(payload, Mapping):
        return [Ignorado("payload nao e um objeto")]
    objeto = payload.get("object")
    if objeto != "instagram":
        return [Ignorado(f"objeto {objeto or '(vazio)'} nao tratado")]
    entradas = payload.get("entry")
    if not isinstance(entradas, list) or not entradas:
        return [Ignorado("sem entry")]

    resultados: list[Resultado] = []
    for entrada in entradas:
        resultados.extend(_entrada(entrada, loja_da_conta))
    return resultados


def _entrada(entrada: object, loja_da_conta: Callable[[str], UUID | None]) -> list[Resultado]:
    if not isinstance(entrada, Mapping):
        return [Ignorado("entry malformada")]
    conta = str(entrada.get("id") or "")
    loja_id = loja_da_conta(conta) if conta else None
    if loja_id is None:
        return [Ignorado(f"conta {conta or '(vazia)'} desconhecida")]
    eventos = entrada.get("messaging")
    if not isinstance(eventos, list) or not eventos:
        return [Ignorado("entry sem messaging")]
    return [_evento(evento, loja_id) for evento in eventos]


def _evento(evento: object, loja_id: UUID) -> Resultado:
    if not isinstance(evento, Mapping):
        return Ignorado("evento malformado")
    mensagem = evento.get("message")
    if not isinstance(mensagem, Mapping):
        tipo = next((k for k in ("reaction", "read", "postback") if k in evento), "desconhecido")
        return Ignorado(f"evento {tipo} nao e mensagem")
    if mensagem.get("is_echo"):
        return Ignorado("eco de mensagem enviada pela propria conta")
    if mensagem.get("is_deleted"):
        return Ignorado("mensagem apagada")
    if mensagem.get("is_unsupported"):
        return Ignorado("mensagem nao suportada pelo Instagram")
    mid = _texto(mensagem.get("mid"))
    if mid is None:
        return Ignorado("mensagem sem mid")
    remetente = evento.get("sender")
    cliente = _texto(remetente.get("id")) if isinstance(remetente, Mapping) else None
    if cliente is None:
        return Ignorado("evento sem sender.id")

    conteudo = _conteudo(mensagem)
    if isinstance(conteudo, Ignorado):
        return conteudo
    tipo, texto, midia_url = conteudo
    return MensagemEntrada(
        loja_id=loja_id,
        canal=Canal.INSTAGRAM,
        id_externo=mid,
        remetente=cliente,
        tipo=tipo,
        texto=texto,
        midia_url=midia_url,
        recebida_em=_instante(evento.get("timestamp")),
    )


def _conteudo(
    mensagem: Mapping[str, Any],
) -> tuple[TipoMensagem, str | None, str | None] | Ignorado:
    """`(tipo, texto, midia_url)`; o texto de uma midia e a legenda."""
    texto = _texto(mensagem.get("text"))
    anexos = mensagem.get("attachments")
    if not isinstance(anexos, list) or not anexos:
        if texto is None:
            return Ignorado("mensagem sem texto nem anexo")
        return TipoMensagem.TEXTO, texto, None
    for anexo in anexos:
        if not isinstance(anexo, Mapping):
            continue
        tipo = _ANEXOS.get(str(anexo.get("type")))
        carga = anexo.get("payload")
        url = _texto(carga.get("url")) if isinstance(carga, Mapping) else None
        if tipo is not None and url is not None:
            return tipo, texto, url
    if texto is not None:
        return TipoMensagem.TEXTO, texto, None
    return Ignorado("anexo nao suportado")


def _texto(valor: object) -> str | None:
    return valor.strip() or None if isinstance(valor, str) else None


def _instante(valor: object) -> datetime:
    """`timestamp` do evento vem em milissegundos."""
    try:
        return datetime.fromtimestamp(int(valor) / 1000, UTC)  # type: ignore[call-overload]
    except (TypeError, ValueError, OverflowError, OSError):
        return datetime.now(UTC)
