"""TTS pela API da OpenAI (`POST /v1/audio/speech`, modelo `gpt-4o-mini-tts`).

Por que este: voz em portugues do Brasil natural, aceita `instructions` (tom/sotaque) e entrega
`opus` (Ogg/Opus) nativo, o formato da nota de voz do WhatsApp, entao nao precisa de ffmpeg.

Preco (referencia, anuncio do modelo em 2025; CONFERIR em https://openai.com/api/pricing antes de
contar com o valor): tokens de texto de entrada + tokens de audio de saida, estimado em cerca de
US$ 0,015 por minuto de fala. Uma resposta de vendas (~15 s) custa uma fracao de centavo.
O custo e controlado por `LIMITE_CARACTERES_FALA` (respostas longas seguem so em texto).
"""

from __future__ import annotations

import httpx

from app.application.audio_saida import TIPO_MIME_AUDIO, AudioSintetizado, ErroTTS

INSTRUCOES = (
    "Fale em português do Brasil, com sotaque neutro, tom simpático e natural de vendedor "
    "atencioso, em ritmo de conversa de WhatsApp. Leia valores em reais de forma natural."
)


def criar_cliente_http(*, timeout_s: float = 30.0) -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url="https://api.openai.com", timeout=timeout_s)


class TTSOpenAI:
    """Implementa `TTSPort`."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        api_key: str,
        modelo: str = "gpt-4o-mini-tts",
        voz: str = "coral",
    ) -> None:
        self._client = client
        self._api_key = api_key
        self._modelo = modelo
        self._voz = voz

    async def sintetizar(self, texto: str) -> AudioSintetizado:
        try:
            resposta = await self._client.post(
                "/v1/audio/speech",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={
                    "model": self._modelo,
                    "voice": self._voz,
                    "input": texto,
                    "instructions": INSTRUCOES,
                    "response_format": "opus",
                },
            )
        except httpx.HTTPError as exc:
            raise ErroTTS(f"TTS inacessivel: {type(exc).__name__}") from exc
        if resposta.status_code >= 400:
            raise ErroTTS(f"TTS respondeu {resposta.status_code}: {resposta.text[:200]}")
        if not resposta.content:
            raise ErroTTS("TTS devolveu audio vazio")
        return AudioSintetizado(resposta.content, TIPO_MIME_AUDIO)
