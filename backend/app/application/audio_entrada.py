"""Audio de entrada: porta de transcricao (STT) e o caso de uso que o agente usa.

O audio do cliente e transcrito ANTES do agente; qualquer problema (midia sumida, API fora,
sem chave, audio sem fala) vira `FalhaTranscricao` e o orquestrador pede ao cliente que digite.
"""

from __future__ import annotations

from typing import Protocol

from app.application.midia import ArmazenamentoMidia


class FalhaTranscricao(Exception):
    """Nao foi possivel transformar o audio em texto (o motivo vai na mensagem, para o log)."""


class STTPort(Protocol):
    async def transcrever(self, audio: bytes, tipo_mime: str) -> str:
        """Texto falado no audio; levanta `FalhaTranscricao` se nao der."""
        ...


def nome_da_midia(midia_url: str) -> str:
    """`http://api/midias/<nome>?x=1` -> `<nome>` (o armazenamento so conhece o nome)."""
    return midia_url.split("?", 1)[0].rsplit("/", 1)[-1] if midia_url else ""


class TranscreverAudio:
    """Le a midia no armazenamento e transcreve. `stt=None` = STT nao configurado (falha)."""

    def __init__(self, stt: STTPort | None, armazenamento: ArmazenamentoMidia) -> None:
        self._stt = stt
        self._armazenamento = armazenamento

    async def __call__(self, midia_url: str) -> str:
        if self._stt is None:
            raise FalhaTranscricao("STT nao configurado")
        nome = nome_da_midia(midia_url)
        conteudo = await self._armazenamento.ler(nome) if nome else None
        if conteudo is None:
            raise FalhaTranscricao(f"audio nao encontrado: {nome!r}")
        texto = (await self._stt.transcrever(conteudo.dados, conteudo.tipo_mime)).strip()
        if not texto:
            raise FalhaTranscricao("audio sem fala reconhecivel")
        return texto
