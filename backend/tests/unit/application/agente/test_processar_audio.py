"""Audio do cliente: transcrito antes do agente; falha no STT pede para o cliente digitar."""

from __future__ import annotations

from app.adapters.outbound.audio.stt_fake import STTFake
from app.application.agente.processar_conversa import (
    MENSAGEM_PEDIR_TEXTO,
    PREFIXO_AUDIO_TRANSCRITO,
)
from app.application.audio_entrada import FalhaTranscricao, TranscreverAudio
from app.application.llm import BlocoTexto
from app.application.midia import ConteudoMidia

from .apoio_processar import Cenario, criar_cenario, texto

NOME = "b" * 32 + ".ogg"
URL = f"http://api.local/midias/{NOME}"


class _Armazenamento:
    async def salvar(self, dados: bytes, tipo_mime: str) -> str:
        raise NotImplementedError

    async def ler(self, nome: str) -> ConteudoMidia | None:
        return ConteudoMidia(b"audio", "audio/ogg") if nome == NOME else None


async def _cenario(stt: STTFake | None, roteiro: list[object] | None = None) -> Cenario:
    return await criar_cenario(
        roteiro or [texto("Temos sim! Qual capacidade?")],  # type: ignore[arg-type]
        transcrever=TranscreverAudio(stt, _Armazenamento()),
    )


def _blocos_do_usuario(c: Cenario) -> list[str]:
    return [b.texto for b in c.llm.chamadas[0].mensagens[0].blocos if isinstance(b, BlocoTexto)]


async def test_audio_vira_texto_no_contexto_do_agente() -> None:
    stt = STTFake("tem iphone 16 de 128?")
    c = await _cenario(stt)
    c.conversas.adicionar_entrada(c.conversa_id, None, tipo="audio", midia_url=URL)
    await c.caso(c.conversa_id)

    assert _blocos_do_usuario(c) == [f"{PREFIXO_AUDIO_TRANSCRITO} tem iphone 16 de 128?"]
    assert c.canal.textos == ["Temos sim! Qual capacidade?"]
    assert len(stt.chamadas) == 1


async def test_transcricao_e_salva_na_mensagem() -> None:
    c = await _cenario(STTFake("oi, tudo bem?"))
    entrada = c.conversas.adicionar_entrada(c.conversa_id, None, tipo="audio", midia_url=URL)
    await c.caso(c.conversa_id)
    assert c.conversas.transcricoes == {entrada.id: "oi, tudo bem?"}


async def test_transcricao_ja_salva_nao_chama_o_stt_de_novo() -> None:
    stt = STTFake("nao deveria ser usado")
    c = await _cenario(stt)
    c.conversas.adicionar_entrada(
        c.conversa_id, None, tipo="audio", midia_url=URL, transcricao="ja transcrito"
    )
    await c.caso(c.conversa_id)
    assert stt.chamadas == []
    assert _blocos_do_usuario(c) == [f"{PREFIXO_AUDIO_TRANSCRITO} ja transcrito"]


async def test_audio_junto_com_texto_mantem_a_ordem() -> None:
    c = await _cenario(STTFake("e o preco?"))
    c.conversas.adicionar_entrada(c.conversa_id, "oi", tipo="texto")
    c.conversas.adicionar_entrada(c.conversa_id, None, tipo="audio", midia_url=URL)
    await c.caso(c.conversa_id)
    assert _blocos_do_usuario(c) == ["oi", f"{PREFIXO_AUDIO_TRANSCRITO} e o preco?"]


async def test_falha_no_stt_pede_para_digitar_sem_chamar_o_llm() -> None:
    c = await _cenario(STTFake(erro=FalhaTranscricao("api fora")))
    c.conversas.adicionar_entrada(c.conversa_id, None, tipo="audio", midia_url=URL)
    await c.caso(c.conversa_id)

    assert c.llm.chamadas == []
    assert c.canal.textos == [MENSAGEM_PEDIR_TEXTO]
    assert "digit" in MENSAGEM_PEDIR_TEXTO
    assert c.conversas.transcricoes == {}
    assert "stt_falha" in c.tipos_de_evento()
    assert c.etapa().value == "novo_contato"  # nao quebra a conversa nem faz handoff
    assert not (await c.atendimento.obter(c.loja_id, c.lead_id)).handoff_solicitado

    # o audio foi consumido: reprocessar sem nada novo nao responde de novo
    await c.caso(c.conversa_id)
    assert c.canal.textos == [MENSAGEM_PEDIR_TEXTO]


async def test_falha_fica_na_transcricao_para_o_proximo_turno() -> None:
    c = await _cenario(
        STTFake(erro=FalhaTranscricao("api fora")), [texto("Perfeito, vou verificar.")]
    )
    c.conversas.adicionar_entrada(c.conversa_id, None, tipo="audio", midia_url=URL)
    await c.caso(c.conversa_id)
    await c.turno("quero iphone 16")
    papeis = [m.papel for m in c.llm.chamadas[0].mensagens]
    assert papeis[:2] == ["user", "assistant"]
    msg_assistente = c.llm.chamadas[0].mensagens[1].blocos[0]
    assert isinstance(msg_assistente, BlocoTexto) and msg_assistente.texto == MENSAGEM_PEDIR_TEXTO


async def test_falha_com_outras_mensagens_segue_para_o_agente_com_instrucao() -> None:
    c = await _cenario(STTFake(erro=FalhaTranscricao("api fora")), [texto("Pode digitar o áudio?")])
    c.conversas.adicionar_entrada(c.conversa_id, "oi", tipo="texto")
    c.conversas.adicionar_entrada(c.conversa_id, None, tipo="audio", midia_url=URL)
    await c.caso(c.conversa_id)

    textos = _blocos_do_usuario(c)
    assert textos[0] == "oi"
    assert "não foi possível transcrever" in textos[1] and "digite" in textos[1]
    assert len(c.llm.chamadas) == 1


async def test_audio_sem_midia_url_conta_como_falha() -> None:
    c = await _cenario(STTFake("x"))
    c.conversas.adicionar_entrada(c.conversa_id, None, tipo="audio")
    await c.caso(c.conversa_id)
    assert c.canal.textos == [MENSAGEM_PEDIR_TEXTO]


async def test_sem_stt_configurado_pede_para_digitar() -> None:
    c = await _cenario(None)
    c.conversas.adicionar_entrada(c.conversa_id, None, tipo="audio", midia_url=URL)
    await c.caso(c.conversa_id)
    assert c.llm.chamadas == []
    assert c.canal.textos == [MENSAGEM_PEDIR_TEXTO]
