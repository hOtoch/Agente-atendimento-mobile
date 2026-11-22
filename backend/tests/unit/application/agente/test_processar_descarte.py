"""Resposta gerada enquanto chegava mensagem nova do cliente: descartada antes de enviar.

A mensagem nova chega no meio da rodada (dentro de uma resposta roteirizada do FakeLLM). O texto
gerado nao vai ao canal nem a transcricao; a proxima rodada responde a tudo junto.
"""

from __future__ import annotations

from collections.abc import Callable
from uuid import uuid4

from app.adapters.outbound.llm.fake import RespostaRoteirizada, Roteiro
from app.application.agente.descartes import DescartesEmMemoria
from app.application.llm import BlocoTexto, MensagemLLM

from .apoio_processar import (
    INTERESSE_16,
    Cenario,
    chamada,
    criar_cenario,
)


def _chega(c: dict[str, Cenario], mensagem: str, resposta: str) -> Roteiro:
    """Resposta do LLM durante a qual o cliente manda `mensagem` (o cenario entra pelo dict)."""

    def roteiro(_: list[MensagemLLM]) -> RespostaRoteirizada:
        c["c"].cliente_diz(mensagem)
        return RespostaRoteirizada(texto=resposta)

    return roteiro


def _textos_do_cliente(msgs: list[MensagemLLM]) -> list[str]:
    return [
        b.texto for m in msgs if m.papel == "user" for b in m.blocos if isinstance(b, BlocoTexto)
    ]


async def _cenario(montar: Callable[[dict[str, Cenario]], list[Roteiro]], **kwargs: int) -> Cenario:
    caixa: dict[str, Cenario] = {}
    c = await criar_cenario(montar(caixa), **kwargs)
    caixa["c"] = c
    return c


async def test_mensagem_no_meio_da_rodada_descarta_a_resposta_sem_enviar() -> None:
    c = await _cenario(lambda x: [_chega(x, "e aceita pix?", "Temos o iPhone 16.")])
    await c.turno("oi, quero um iphone 16")

    assert c.canal.textos == []
    assert c.conversas.saidas == []
    assert not [e for _, e in c.painel.publicados if e.nome == "MensagemNova"]
    assert "resposta_descartada" in c.tipos_de_evento()
    assert "llm_uso" in c.tipos_de_evento()  # os tokens foram gastos: o custo continua visivel
    transcrito = await c.transcricao.listar(c.conversa_id)
    assert not [m for m in transcrito if m.papel == "assistant"]


async def test_proxima_rodada_considera_as_mensagens_antigas_e_as_novas_sem_duplicar() -> None:
    c = await _cenario(
        lambda x: [
            _chega(x, "e aceita pix?", "Temos o iPhone 16."),
            RespostaRoteirizada(texto="Temos sim, e aceitamos pix."),
        ]
    )
    await c.turno("oi, quero um iphone 16")
    await c.caso(c.conversa_id)

    assert c.canal.textos == ["Temos sim, e aceitamos pix."]
    vistas = _textos_do_cliente(c.llm.chamadas[1].mensagens)
    assert [t for t in vistas if "iphone 16" in t].__len__() == 1
    assert [t for t in vistas if "aceita pix" in t].__len__() == 1
    assert "Temos o iPhone 16." not in str(
        c.llm.chamadas[1].mensagens
    )  # o texto descartado nao vaza
    # nada mais pendente: uma terceira passada nao chama o LLM
    await c.caso(c.conversa_id)
    assert len(c.llm.chamadas) == 2


async def test_estado_das_ferramentas_da_rodada_descartada_e_mantido() -> None:
    c = await _cenario(
        lambda x: [
            RespostaRoteirizada(chamadas=[chamada("t1", "registrar_interesse", INTERESSE_16)]),
            _chega(x, "e aceita pix?", "Temos o iPhone 16."),
            RespostaRoteirizada(texto="Temos sim."),
        ]
    )
    await c.turno("oi, quero um iphone 16 128")
    assert c.canal.textos == []
    estado = await c.atendimento.obter(c.loja_id, c.lead_id)
    assert estado.ficha.interesse.modelo is not None  # ferramenta idempotente: mudanca preservada

    await c.caso(c.conversa_id)
    assert c.canal.textos == ["Temos sim."]


async def test_depois_do_limite_de_descartes_a_resposta_sai_mesmo_assim() -> None:
    c = await _cenario(
        lambda x: [
            _chega(x, "msg 2", "R1"),
            _chega(x, "msg 3", "R2"),
            _chega(x, "msg 4", "R3"),
            RespostaRoteirizada(texto="R4"),
        ],
        max_descartes=2,
    )
    await c.turno("msg 1")
    await c.caso(c.conversa_id)
    assert c.canal.textos == []
    await c.caso(c.conversa_id)  # terceira: limite atingido, envia apesar da msg 4 chegando
    assert c.canal.textos == ["R3"]
    assert c.tipos_de_evento().count("resposta_descartada") == 2
    # a msg 4 ficou pendente e e respondida na rodada seguinte
    await c.caso(c.conversa_id)
    assert c.canal.textos == ["R3", "R4"]


async def test_resposta_enviada_zera_a_contagem_de_descartes() -> None:
    c = await _cenario(
        lambda x: [
            _chega(x, "msg 2", "R1"),
            RespostaRoteirizada(texto="R2"),
            _chega(x, "msg 4", "R3"),
            RespostaRoteirizada(texto="R4"),
        ],
        max_descartes=1,
    )
    await c.turno("msg 1")  # descarta (1 de 1)
    await c.caso(c.conversa_id)  # envia R2 e zera
    c.cliente_diz("msg 3")
    await c.caso(c.conversa_id)  # de novo pode descartar
    await c.caso(c.conversa_id)
    assert c.canal.textos == ["R2", "R4"]
    assert c.tipos_de_evento().count("resposta_descartada") == 2


async def test_sem_mensagem_nova_a_resposta_sai_normalmente() -> None:
    c = await criar_cenario([RespostaRoteirizada(texto="Oi!")])
    await c.turno("oi")
    assert c.canal.textos == ["Oi!"]
    assert "resposta_descartada" not in c.tipos_de_evento()


async def test_handoff_pedido_na_rodada_nao_e_descartado() -> None:
    caixa: dict[str, Cenario] = {}

    def chamar(_: list[MensagemLLM]) -> RespostaRoteirizada:
        return RespostaRoteirizada(
            chamadas=[chamada("t1", "chamar_vendedor", {"motivo": "quer fechar"})]
        )

    c = await criar_cenario(
        [
            chamar,
            _chega(caixa, "alo?", "Vou chamar um vendedor para você 🙂"),
            RespostaRoteirizada(texto="Resumo do handoff."),
        ]
    )
    caixa["c"] = c
    await c.turno("quero fechar")
    assert c.canal.textos == ["Vou chamar um vendedor para você 🙂"]
    assert "resposta_descartada" not in c.tipos_de_evento()


async def test_contador_compartilhado_entre_instancias_limita_os_descartes() -> None:
    contador = DescartesEmMemoria()
    c1, c2 = uuid4(), uuid4()
    assert await contador.registrar(c1) == 1
    assert await contador.registrar(c1) == 2
    assert await contador.registrar(c2) == 1
    await contador.zerar(c1)
    assert await contador.registrar(c1) == 1
    assert await contador.atual(c1) == 1
