"""Adaptador TTS da OpenAI: contrato HTTP verificado com MockTransport (nunca rede real)."""

from __future__ import annotations

import json

import httpx
import pytest

from app.adapters.outbound.audio.tts_openai import TTSOpenAI
from app.application.audio_saida import ErroTTS


def _tts(handler: httpx.MockTransport, **kw: str) -> TTSOpenAI:
    cliente = httpx.AsyncClient(transport=handler, base_url="https://api.openai.com")
    return TTSOpenAI(cliente, api_key="sk-teste", **kw)


async def test_envia_modelo_voz_formato_opus_e_devolve_audio_ogg() -> None:
    vistas: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        vistas.append(req)
        return httpx.Response(200, content=b"OggS-bytes", headers={"content-type": "audio/ogg"})

    audio = await _tts(
        httpx.MockTransport(handler), modelo="gpt-4o-mini-tts", voz="coral"
    ).sintetizar("Oi, tudo bem?")

    assert audio.dados == b"OggS-bytes"
    assert audio.tipo_mime == "audio/ogg"
    req = vistas[0]
    assert req.method == "POST"
    assert req.url.path == "/v1/audio/speech"
    assert req.headers["authorization"] == "Bearer sk-teste"
    corpo = json.loads(req.content)
    assert corpo["model"] == "gpt-4o-mini-tts"
    assert corpo["voice"] == "coral"
    assert corpo["input"] == "Oi, tudo bem?"
    assert corpo["response_format"] == "opus"
    assert "portugu" in corpo["instructions"].lower()


async def test_voz_padrao_e_masculina_com_instrucoes_de_fala_natural() -> None:
    vistas: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        vistas.append(req)
        return httpx.Response(200, content=b"OggS-bytes")

    await _tts(httpx.MockTransport(handler)).sintetizar("Oi")

    corpo = json.loads(vistas[0].content)
    assert corpo["voice"] == "cedar"
    instrucoes = corpo["instructions"].lower()
    assert "masculin" in instrucoes
    assert "natural" in instrucoes


async def test_status_de_erro_vira_erro_tts_sem_vazar_a_chave() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": {"message": "rate limit"}})

    with pytest.raises(ErroTTS) as exc:
        await _tts(httpx.MockTransport(handler)).sintetizar("oi")
    assert "429" in str(exc.value)
    assert "sk-teste" not in str(exc.value)


async def test_falha_de_rede_vira_erro_tts() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("sem rede")

    with pytest.raises(ErroTTS):
        await _tts(httpx.MockTransport(handler)).sintetizar("oi")


async def test_resposta_vazia_vira_erro_tts() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"")

    with pytest.raises(ErroTTS):
        await _tts(httpx.MockTransport(handler)).sintetizar("oi")
