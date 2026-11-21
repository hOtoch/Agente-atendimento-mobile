"""STT falso para os testes do projeto inteiro (nunca toca a rede)."""

from __future__ import annotations

from app.application.audio_entrada import FalhaTranscricao


class STTFake:
    """Devolve `texto` fixo; se `erro` for dado, levanta-o. Guarda o que recebeu."""

    def __init__(self, texto: str = "", *, erro: FalhaTranscricao | None = None) -> None:
        self._texto = texto
        self._erro = erro
        self.chamadas: list[tuple[bytes, str]] = []

    async def transcrever(self, audio: bytes, tipo_mime: str) -> str:
        self.chamadas.append((audio, tipo_mime))
        if self._erro is not None:
            raise self._erro
        return self._texto
