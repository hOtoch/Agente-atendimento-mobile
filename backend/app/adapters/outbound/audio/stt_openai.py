"""STT pela API de transcricao da OpenAI (`gpt-4o-mini-transcribe`), via httpx.

Escolha (custo/qualidade em pt-BR): `gpt-4o-mini-transcribe` e a opcao barata da familia
`gpt-4o-*-transcribe`, que supera o `whisper-1` em taxa de erro nos benchmarks multilingues da
OpenAI. Preco de referencia (nov/2026, de memoria do projeto, NAO verificado em tempo real):
cerca de US$ 0,003 por minuto de audio, contra ~US$ 0,006 do `gpt-4o-transcribe` e do `whisper-1`.
Um audio de WhatsApp de 20 s custa ~US$ 0,001. Conferir em https://openai.com/api/pricing antes de
escalar. O modelo e trocavel por `STT_MODEL` e a chave vem de `OPENAI_API_KEY` (vazia = STT
indisponivel, mesma rota da falha: o agente pede para o cliente digitar).
"""

from __future__ import annotations

import httpx

from app.application.audio_entrada import FalhaTranscricao

_ROTA = "/v1/audio/transcriptions"
_EXTENSAO_POR_TIPO = {
    "audio/webm": "webm",
    "audio/ogg": "ogg",
    "audio/mpeg": "mp3",
    "audio/mp4": "m4a",
}


def criar_cliente_http(*, timeout_s: float = 30.0) -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url="https://api.openai.com", timeout=timeout_s)


class STTOpenAI:
    """Implementa `STTPort`. Nunca vaza o corpo de erro da API (so o status) para quem chama."""

    def __init__(self, client: httpx.AsyncClient, *, api_key: str | None, modelo: str) -> None:
        self._client = client
        self._api_key = api_key
        self._modelo = modelo

    async def transcrever(self, audio: bytes, tipo_mime: str) -> str:
        if not self._api_key:
            raise FalhaTranscricao("OPENAI_API_KEY nao configurada")
        extensao = _EXTENSAO_POR_TIPO.get(tipo_mime, "bin")
        try:
            resposta = await self._client.post(
                _ROTA,
                headers={"Authorization": f"Bearer {self._api_key}"},
                data={"model": self._modelo, "language": "pt", "response_format": "json"},
                files={"file": (f"audio.{extensao}", audio, tipo_mime)},
            )
        except httpx.HTTPError as exc:
            raise FalhaTranscricao(f"OpenAI inacessivel: {type(exc).__name__}") from exc
        if resposta.status_code != 200:
            raise FalhaTranscricao(f"OpenAI respondeu {resposta.status_code} na transcricao")
        try:
            corpo = resposta.json()
            texto = corpo["text"]
        except (ValueError, KeyError, TypeError) as exc:
            raise FalhaTranscricao("resposta inesperada da OpenAI na transcricao") from exc
        if not isinstance(texto, str):
            raise FalhaTranscricao("resposta inesperada da OpenAI na transcricao")
        return texto.strip()
