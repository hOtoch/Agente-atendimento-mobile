"""Adaptador OpenAI de STT: `httpx.MockTransport`, nenhum teste toca a rede."""

from __future__ import annotations

import json
from collections.abc import Callable

import httpx
import pytest

from app.adapters.outbound.audio.stt_openai import STTOpenAI
from app.application.audio_entrada import FalhaTranscricao, STTPort

Handler = Callable[[httpx.Request], httpx.Response]


def _stt(handler: Handler, *, api_key: str | None = "sk-teste") -> STTOpenAI:
    cliente = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://api.openai.test"
    )
    return STTOpenAI(cliente, api_key=api_key, modelo="gpt-4o-mini-transcribe")


def test_implementa_a_porta() -> None:
    def _aceita(s: STTPort) -> None: ...

    _aceita(_stt(lambda r: httpx.Response(200)))


async def test_envia_multipart_e_le_o_texto() -> None:
    vistos: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        vistos.append(req)
        return httpx.Response(200, json={"text": " quero um iphone 16 "})

    texto = await _stt(handler).transcrever(b"AUDIO", "audio/ogg")

    assert texto == "quero um iphone 16"
    req = vistos[0]
    assert req.method == "POST" and req.url.path == "/v1/audio/transcriptions"
    assert req.headers["authorization"] == "Bearer sk-teste"
    assert req.headers["content-type"].startswith("multipart/form-data")
    corpo = req.content
    assert b'name="model"' in corpo and b"gpt-4o-mini-transcribe" in corpo
    assert b'name="language"' in corpo and b"pt" in corpo
    assert b'filename="audio.ogg"' in corpo and b"AUDIO" in corpo
    assert b"audio/ogg" in corpo


@pytest.mark.parametrize(
    ("mime", "extensao"),
    [
        ("audio/webm", "webm"),
        ("audio/ogg", "ogg"),
        ("audio/mpeg", "mp3"),
        ("audio/mp4", "m4a"),
    ],
)
async def test_extensao_do_arquivo_segue_o_tipo(mime: str, extensao: str) -> None:
    vistos: list[bytes] = []

    def handler(req: httpx.Request) -> httpx.Response:
        vistos.append(req.content)
        return httpx.Response(200, json={"text": "ok"})

    await _stt(handler).transcrever(b"x", mime)
    assert f'filename="audio.{extensao}"'.encode() in vistos[0]


async def test_sem_chave_falha_sem_chamar_a_api() -> None:
    chamadas: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        chamadas.append(req)
        return httpx.Response(200, json={"text": "x"})

    for chave in (None, ""):
        with pytest.raises(FalhaTranscricao):
            await _stt(handler, api_key=chave).transcrever(b"x", "audio/ogg")
    assert chamadas == []


@pytest.mark.parametrize("status", [400, 401, 429, 500, 503])
async def test_erro_http_vira_falha_transcricao(status: int) -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"error": {"message": "segredo-da-api"}})

    with pytest.raises(FalhaTranscricao) as exc:
        await _stt(handler).transcrever(b"x", "audio/ogg")
    assert str(status) in str(exc.value)


async def test_erro_de_rede_vira_falha_transcricao() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("lento", request=req)

    with pytest.raises(FalhaTranscricao):
        await _stt(handler).transcrever(b"x", "audio/ogg")


@pytest.mark.parametrize("corpo", ["nao e json", json.dumps({"sem_texto": 1}), json.dumps([1])])
async def test_resposta_inesperada_vira_falha_transcricao(corpo: str) -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=corpo.encode())

    with pytest.raises(FalhaTranscricao):
        await _stt(handler).transcrever(b"x", "audio/ogg")
