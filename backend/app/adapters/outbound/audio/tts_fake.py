"""TTS falso para testes e demos: nunca toca a rede nem cobra."""

from __future__ import annotations

from app.application.audio_saida import TIPO_MIME_AUDIO, AudioSintetizado, ErroTTS


class TTSFake:
    """Implementa `TTSPort`. `erro` (se houver) e levantado no lugar de sintetizar."""

    def __init__(self, *, erro: ErroTTS | None = None, dados: bytes = b"OggS-fake") -> None:
        self.erro = erro
        self.dados = dados
        self.textos: list[str] = []

    async def sintetizar(self, texto: str) -> AudioSintetizado:
        self.textos.append(texto)
        if self.erro is not None:
            raise self.erro
        return AudioSintetizado(self.dados, TIPO_MIME_AUDIO)
