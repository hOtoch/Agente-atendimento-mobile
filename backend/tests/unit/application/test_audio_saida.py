"""Resposta em audio: regra de quando usar, texto da fala e caso de uso (TTS fake em memoria)."""

from __future__ import annotations

import pytest

from app.adapters.outbound.audio.tts_fake import TTSFake
from app.application.audio_saida import (
    LIMITE_CARACTERES_FALA,
    AudioSintetizado,
    ErroTTS,
    ResponderEmAudio,
    deve_responder_em_audio,
    texto_para_fala,
)
from app.application.midia import ConteudoMidia


class ArmazenamentoMemoria:
    def __init__(self) -> None:
        self.itens: dict[str, ConteudoMidia] = {}

    async def salvar(self, dados: bytes, tipo_mime: str) -> str:
        nome = f"a{len(self.itens)}"
        self.itens[nome] = ConteudoMidia(dados=dados, tipo_mime=tipo_mime)
        return nome

    async def ler(self, nome: str) -> ConteudoMidia | None:
        return self.itens.get(nome)


# --- regra de quando usar audio ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("ultima_foi_audio", "loja_ligada", "tts_disponivel", "esperado"),
    [
        (True, True, True, True),
        (False, True, True, False),  # cliente escreveu: responde so em texto
        (True, False, True, False),  # loja desligou a opcao
        (True, True, False, False),  # sem TTS configurado
        (False, False, False, False),
    ],
)
def test_regra_de_quando_responder_em_audio(
    ultima_foi_audio: bool, loja_ligada: bool, tts_disponivel: bool, esperado: bool
) -> None:
    assert (
        deve_responder_em_audio(
            ultima_entrada_foi_audio=ultima_foi_audio,
            loja_ligada=loja_ligada,
            tts_disponivel=tts_disponivel,
        )
        is esperado
    )


# --- texto da fala ----------------------------------------------------------------------------


def test_texto_para_fala_tira_emoji_e_marcacao_mas_mantem_valores() -> None:
    fala = texto_para_fala("Fechou! 🎉 O **iPhone 16** sai por *R$ 4.599,00* no Pix 🙂")
    assert fala == "Fechou! O iPhone 16 sai por R$ 4.599,00 no Pix"


def test_texto_para_fala_vazio_ou_so_emoji_vira_none() -> None:
    assert texto_para_fala("   ") is None
    assert texto_para_fala("🙂🙂") is None


def test_texto_longo_demais_nao_vira_fala() -> None:
    assert texto_para_fala("a" * (LIMITE_CARACTERES_FALA + 1)) is None
    assert texto_para_fala("a" * LIMITE_CARACTERES_FALA) is not None


# --- fake -------------------------------------------------------------------------------------


async def test_fake_registra_os_textos_e_devolve_audio_ogg() -> None:
    tts = TTSFake()
    audio = await tts.sintetizar("Oi, tudo bem?")
    assert tts.textos == ["Oi, tudo bem?"]
    assert audio.tipo_mime == "audio/ogg"
    assert audio.dados  # nao vazio


async def test_fake_pode_falhar_como_a_api() -> None:
    tts = TTSFake(erro=ErroTTS("fora do ar"))
    with pytest.raises(ErroTTS):
        await tts.sintetizar("x")


# --- caso de uso ------------------------------------------------------------------------------


async def test_gera_guarda_e_devolve_a_url_da_midia() -> None:
    tts, arm = TTSFake(), ArmazenamentoMemoria()
    caso = ResponderEmAudio(tts, arm, base_midia="http://api.local/")

    url = await caso("O iPhone sai por R$ 4.599,00 🙂")

    assert url == "http://api.local/midias/a0"
    assert tts.textos == ["O iPhone sai por R$ 4.599,00"]
    assert arm.itens["a0"] == ConteudoMidia(dados=tts.dados, tipo_mime="audio/ogg")


async def test_falha_do_tts_devolve_none_sem_levantar() -> None:
    arm = ArmazenamentoMemoria()
    caso = ResponderEmAudio(TTSFake(erro=ErroTTS("x")), arm, base_midia="http://api.local")
    assert await caso("oi") is None
    assert arm.itens == {}


async def test_texto_sem_fala_nao_chama_o_tts() -> None:
    tts = TTSFake()
    caso = ResponderEmAudio(tts, ArmazenamentoMemoria(), base_midia="http://api.local")
    assert await caso("🙂") is None
    assert tts.textos == []


def test_audio_sintetizado_e_valor_imutavel() -> None:
    a = AudioSintetizado(b"x", "audio/ogg")
    with pytest.raises(AttributeError):
        a.dados = b"y"  # type: ignore[misc]
