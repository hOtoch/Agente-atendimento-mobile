"""Caso de uso `TranscreverAudio`: bytes da midia -> STT -> texto (ou `FalhaTranscricao`)."""

from __future__ import annotations

import pytest

from app.adapters.outbound.audio.stt_fake import STTFake
from app.application.audio_entrada import (
    FalhaTranscricao,
    STTPort,
    TranscreverAudio,
    nome_da_midia,
)
from app.application.midia import ConteudoMidia


class ArmazenamentoFalso:
    def __init__(self, arquivos: dict[str, ConteudoMidia] | None = None) -> None:
        self.arquivos = arquivos or {}

    async def salvar(self, dados: bytes, tipo_mime: str) -> str:
        raise NotImplementedError

    async def ler(self, nome: str) -> ConteudoMidia | None:
        return self.arquivos.get(nome)


NOME = "a" * 32 + ".ogg"
URL = f"http://api.local/midias/{NOME}"


def _armazenamento() -> ArmazenamentoFalso:
    return ArmazenamentoFalso({NOME: ConteudoMidia(b"bytes-do-audio", "audio/ogg")})


def test_fake_implementa_a_porta() -> None:
    def _aceita(s: STTPort) -> None: ...

    _aceita(STTFake("oi"))


@pytest.mark.parametrize(
    ("url", "esperado"),
    [
        (URL, NOME),
        (f"{URL}?x=1", NOME),
        (NOME, NOME),
        ("http://api.local/midias/", ""),
    ],
)
def test_nome_da_midia(url: str, esperado: str) -> None:
    assert nome_da_midia(url) == esperado


async def test_audio_vira_texto() -> None:
    stt = STTFake("quero um iphone 16")
    texto = await TranscreverAudio(stt, _armazenamento())(URL)
    assert texto == "quero um iphone 16"
    assert stt.chamadas == [(b"bytes-do-audio", "audio/ogg")]


async def test_transcricao_vem_sem_espacos_nas_pontas() -> None:
    assert await TranscreverAudio(STTFake("  oi \n"), _armazenamento())(URL) == "oi"


async def test_falha_do_stt_sobe_como_falha_transcricao() -> None:
    caso = TranscreverAudio(STTFake(erro=FalhaTranscricao("api fora")), _armazenamento())
    with pytest.raises(FalhaTranscricao):
        await caso(URL)


async def test_midia_inexistente_e_falha() -> None:
    stt = STTFake("x")
    with pytest.raises(FalhaTranscricao):
        await TranscreverAudio(stt, ArmazenamentoFalso())(URL)
    assert stt.chamadas == []


async def test_audio_sem_fala_e_falha() -> None:
    with pytest.raises(FalhaTranscricao):
        await TranscreverAudio(STTFake("   "), _armazenamento())(URL)


async def test_sem_stt_configurado_e_falha() -> None:
    with pytest.raises(FalhaTranscricao):
        await TranscreverAudio(None, _armazenamento())(URL)
