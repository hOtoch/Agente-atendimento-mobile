"""Resposta em audio (TTS): porta, regra de quando usar e caso de uso.

Regras (decididas pelo CODIGO, nao pelo LLM):
- a resposta sai SEMPRE em texto (precos e valores tambem por escrito); o audio e um extra;
- o audio so e gerado quando o cliente mandou audio na ULTIMA mensagem, a loja deixou a opcao
  ligada e ha um TTS configurado;
- qualquer falha do TTS vira "so texto": nunca derruba o atendimento.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Protocol

from app.application.midia import ArmazenamentoMidia

log = logging.getLogger(__name__)

LIMITE_CARACTERES_FALA = 1200
"""Acima disso a resposta nao vira audio (fala longa demais e custa mais); segue so em texto."""

TIPO_MIME_AUDIO = "audio/ogg"


class ErroTTS(Exception):
    """O provedor de voz falhou (rede, quota, resposta invalida)."""


@dataclass(frozen=True, slots=True)
class AudioSintetizado:
    dados: bytes
    tipo_mime: str


class TTSPort(Protocol):
    async def sintetizar(self, texto: str) -> AudioSintetizado:
        """Texto -> audio de nota de voz (ogg/opus). Levanta `ErroTTS` se falhar."""
        ...


def deve_responder_em_audio(
    *, ultima_entrada_foi_audio: bool, loja_ligada: bool, tts_disponivel: bool
) -> bool:
    return ultima_entrada_foi_audio and loja_ligada and tts_disponivel


# Emojis, simbolos e pictogramas (nao falados) + marcacao de negrito/italico do WhatsApp/Markdown.
_NAO_FALADO = re.compile("[\U0001f000-\U0001faff☀-➿⌀-⏿⬀-⯿️‍]|[*_~`#]")


def texto_para_fala(texto: str) -> str | None:
    """Limpa o texto para a voz. `None` quando nao ha o que falar ou e longo demais."""
    fala = re.sub(r"\s+", " ", _NAO_FALADO.sub("", texto)).strip()
    if not fala or len(fala) > LIMITE_CARACTERES_FALA:
        return None
    return fala


class ResponderEmAudio:
    """Gera a fala, guarda na midia da loja e devolve a URL publica (ou `None`)."""

    def __init__(self, tts: TTSPort, armazenamento: ArmazenamentoMidia, *, base_midia: str) -> None:
        self._tts = tts
        self._armazenamento = armazenamento
        self._base = base_midia.rstrip("/")

    async def __call__(self, texto: str) -> str | None:
        fala = texto_para_fala(texto)
        if fala is None:
            return None
        try:
            audio = await self._tts.sintetizar(fala)
            nome = await self._armazenamento.salvar(audio.dados, audio.tipo_mime)
        except Exception:
            log.exception("falha ao gerar a resposta em audio; seguindo so com o texto")
            return None
        return f"{self._base}/midias/{nome}"
