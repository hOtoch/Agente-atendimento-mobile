"""Normaliza o payload do webhook da Evolution API v2 (`messages.upsert`).

Funcao pura: nunca estoura. O que nao interessa (grupo, status, figurinha, reacao, eventos de
conexao, instancia de outra loja) volta como `Ignorado` com o motivo, e o webhook responde 200
para a Evolution nao reenviar.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.application.canal import TipoMensagem
from app.application.whatsapp import EventoMensagemWhatsApp, loja_da_instancia

_EVENTO_MENSAGEM = "messages.upsert"
_EMBRULHOS = (
    "ephemeralMessage",
    "viewOnceMessage",
    "viewOnceMessageV2",
    "viewOnceMessageV2Extension",
    "documentWithCaptionMessage",
)
_JID_DE_CONTATO = ("@s.whatsapp.net", "@lid")


@dataclass(frozen=True, slots=True)
class Ignorado:
    motivo: str


def normalizar(payload: object) -> EventoMensagemWhatsApp | Ignorado:
    if not isinstance(payload, Mapping):
        return Ignorado("payload nao e um objeto")
    evento = str(payload.get("event", "")).lower().replace("_", ".")
    if evento != _EVENTO_MENSAGEM:
        return Ignorado(f"evento {evento or '(vazio)'} nao tratado")
    loja_id = loja_da_instancia(str(payload.get("instance", "")))
    if loja_id is None:
        return Ignorado("instancia desconhecida")
    dados = payload.get("data")
    if not isinstance(dados, Mapping):
        return Ignorado("sem data")
    chave = dados.get("key")
    if not isinstance(chave, Mapping) or not chave.get("id"):
        return Ignorado("sem key.id")

    contato = _contato(chave)
    if isinstance(contato, Ignorado):
        return contato
    conteudo = _conteudo(_desembrulhar(dados.get("message")))
    if isinstance(conteudo, Ignorado):
        return conteudo
    tipo, texto, tipo_mime, baixar = conteudo

    de_mim = bool(chave.get("fromMe"))
    nome = dados.get("pushName")
    return EventoMensagemWhatsApp(
        loja_id=loja_id,
        id_whatsapp=str(chave["id"]),
        de_mim=de_mim,
        contato=contato,
        # O pushName de uma mensagem minha e o nome da loja, nao o do cliente.
        nome=nome.strip() if isinstance(nome, str) and nome.strip() and not de_mim else None,
        tipo=tipo,
        texto=texto,
        tipo_mime=tipo_mime,
        baixar_midia=baixar,
        recebida_em=_instante(dados.get("messageTimestamp")),
    )


def _contato(chave: Mapping[str, Any]) -> str | Ignorado:
    jid = str(chave.get("remoteJid", ""))
    if jid.endswith("@g.us"):
        return Ignorado("mensagem de grupo")
    if jid == "status@broadcast" or jid.endswith("@broadcast"):
        return Ignorado("status/lista de transmissao")
    if jid.endswith("@lid"):
        # Contas com privacidade por LID: o numero real vem em campos alternativos.
        alternativo = chave.get("remoteJidAlt") or chave.get("senderPn")
        if isinstance(alternativo, str) and alternativo.endswith("@s.whatsapp.net"):
            jid = alternativo
    if not jid.endswith(_JID_DE_CONTATO):
        return Ignorado(f"remoteJid nao suportado: {jid or '(vazio)'}")
    numero = jid.split("@", 1)[0].split(":", 1)[0]
    if not numero.isdigit():
        return Ignorado("remoteJid sem telefone")
    return numero


def _desembrulhar(mensagem: object) -> Mapping[str, Any]:
    """Abre os envelopes (efemera, visualizacao unica, documento com legenda)."""
    atual = mensagem if isinstance(mensagem, Mapping) else {}
    for _ in range(4):
        for nome in _EMBRULHOS:
            envelope = atual.get(nome)
            if isinstance(envelope, Mapping):
                interna = envelope.get("message")
                atual = interna if isinstance(interna, Mapping) else {}
                break
        else:
            return atual
    return atual


def _texto(valor: object) -> str | None:
    return valor.strip() or None if isinstance(valor, str) else None


def _conteudo(
    m: Mapping[str, Any],
) -> tuple[TipoMensagem, str | None, str | None, bool] | Ignorado:
    """`(tipo, texto, tipo_mime, baixar_midia)`."""
    if (texto := _texto(m.get("conversation"))) is not None:
        return TipoMensagem.TEXTO, texto, None, False
    estendida = m.get("extendedTextMessage")
    if isinstance(estendida, Mapping):
        texto = _texto(estendida.get("text"))
        return (
            (TipoMensagem.TEXTO, texto, None, False)
            if texto is not None
            else Ignorado("texto vazio")
        )
    imagem = m.get("imageMessage")
    if isinstance(imagem, Mapping):
        mime = _texto(imagem.get("mimetype")) or "image/jpeg"
        return TipoMensagem.IMAGEM, _texto(imagem.get("caption")), mime, True
    audio = m.get("audioMessage")
    if isinstance(audio, Mapping):
        mime = _texto(audio.get("mimetype")) or "audio/ogg; codecs=opus"
        return TipoMensagem.AUDIO, None, mime, True
    documento = m.get("documentMessage")
    if isinstance(documento, Mapping):
        nome = _texto(documento.get("fileName")) or _texto(documento.get("title")) or "arquivo"
        marca = f"[documento recebido: {nome}]"
        legenda = _texto(documento.get("caption"))
        return TipoMensagem.TEXTO, f"{legenda}\n{marca}" if legenda else marca, None, False
    return Ignorado("tipo de mensagem nao suportado")


def _instante(valor: object) -> datetime:
    if isinstance(valor, Mapping):  # protobuf Long: {"low": n, "high": 0}
        valor = valor.get("low")
    try:
        return datetime.fromtimestamp(int(valor), UTC)  # type: ignore[call-overload]
    except (TypeError, ValueError, OverflowError, OSError):
        return datetime.now(UTC)
