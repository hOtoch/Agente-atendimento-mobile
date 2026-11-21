"""Resposta em audio no orquestrador: audio so quando o cliente mandou audio e a loja quer.

O texto sai SEMPRE (precos e valores tambem em texto); o audio e um extra.
"""

from __future__ import annotations

from app.adapters.outbound.audio.tts_fake import TTSFake
from app.application.audio_saida import ErroTTS, ResponderEmAudio
from app.application.canal import TipoMensagem
from app.application.config.modelos import PerfilLoja

from ..test_audio_saida import ArmazenamentoMemoria
from .apoio_processar import Cenario, criar_cenario, texto

BASE = "http://api.local"
RESPOSTA = "O iPhone 16 128GB sai por R$ 4.599,00 no Pix."


async def _cenario(tts: TTSFake | None = None, *, com_audio: bool = True) -> Cenario:
    audio = ResponderEmAudio(tts or TTSFake(), ArmazenamentoMemoria(), base_midia=BASE)
    return await criar_cenario([texto(RESPOSTA)], audio_saida=audio if com_audio else None)


async def _audio_do_cliente(c: Cenario) -> None:
    c.conversas.adicionar_entrada(
        c.conversa_id, None, tipo="audio", midia_url="http://api.local/midias/x.webm"
    )
    await c.caso(c.conversa_id)


async def test_cliente_manda_audio_resposta_em_audio_e_texto_com_valores() -> None:
    tts = TTSFake()
    c = await _cenario(tts)

    await _audio_do_cliente(c)

    tipos = [m.tipo for m in c.canal.enviadas]
    assert tipos == [TipoMensagem.TEXTO, TipoMensagem.AUDIO]
    texto_msg, audio_msg = c.canal.enviadas
    assert texto_msg.texto == RESPOSTA
    assert audio_msg.texto is None
    assert audio_msg.midia_url == f"{BASE}/midias/a0"
    assert tts.textos == [RESPOSTA]
    # as duas saidas ficam registradas na conversa e no painel
    assert [m.tipo for _, m in c.conversas.saidas] == [TipoMensagem.TEXTO, TipoMensagem.AUDIO]
    eventos = [e for _, e in c.painel.publicados if getattr(e, "direcao", None) == "saida"]
    assert [getattr(e, "tipo", None) for e in eventos] == ["texto", "audio"]


async def test_cliente_escreve_so_texto() -> None:
    tts = TTSFake()
    c = await _cenario(tts)
    await c.turno("Quanto custa o iPhone 16?")
    assert [m.tipo for m in c.canal.enviadas] == [TipoMensagem.TEXTO]
    assert tts.textos == []


async def test_configuracao_desligada_so_texto() -> None:
    tts = TTSFake()
    c = await _cenario(tts)
    await c.amb.casos.atualizar_perfil(
        c.loja_id, PerfilLoja("Loja", "", "", {}, "", responder_em_audio=False)
    )

    await _audio_do_cliente(c)

    assert [m.tipo for m in c.canal.enviadas] == [TipoMensagem.TEXTO]
    assert tts.textos == []


async def test_a_configuracao_vale_na_proxima_mensagem() -> None:
    c = await criar_cenario(
        [texto("um"), texto("dois")],
        audio_saida=ResponderEmAudio(TTSFake(), ArmazenamentoMemoria(), base_midia=BASE),
    )
    await _audio_do_cliente(c)
    await c.amb.casos.atualizar_perfil(
        c.loja_id, PerfilLoja("Loja", "", "", {}, "", responder_em_audio=False)
    )
    await _audio_do_cliente(c)
    assert [m.tipo for m in c.canal.enviadas] == [
        TipoMensagem.TEXTO,
        TipoMensagem.AUDIO,
        TipoMensagem.TEXTO,
    ]


async def test_sem_tts_configurado_so_texto() -> None:
    c = await _cenario(com_audio=False)
    await _audio_do_cliente(c)
    assert [m.tipo for m in c.canal.enviadas] == [TipoMensagem.TEXTO]


async def test_falha_do_tts_nao_quebra_a_resposta_em_texto() -> None:
    c = await _cenario(TTSFake(erro=ErroTTS("fora do ar")))
    await _audio_do_cliente(c)
    assert c.canal.textos == [RESPOSTA]
    assert [m.tipo for m in c.canal.enviadas] == [TipoMensagem.TEXTO]


async def test_ultima_mensagem_decide_audio_seguido_de_texto_nao_gera_audio() -> None:
    tts = TTSFake()
    c = await _cenario(tts)
    c.conversas.adicionar_entrada(c.conversa_id, None, tipo="audio", midia_url="http://x/a.webm")
    c.conversas.adicionar_entrada(c.conversa_id, "e o preço?")
    await c.caso(c.conversa_id)
    assert [m.tipo for m in c.canal.enviadas] == [TipoMensagem.TEXTO]
