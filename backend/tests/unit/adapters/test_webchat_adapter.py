"""WebChatAdapter e BarramentoEmMemoria."""

import asyncio
from uuid import UUID

from app.adapters.outbound.barramento.memoria import BarramentoEmMemoria
from app.adapters.outbound.canal.webchat import WebChatAdapter, topico_webchat
from app.application.canal import Canal, MensagemSaida, TipoMensagem

LOJA = UUID(int=7)


async def _primeira(barramento: BarramentoEmMemoria, topico: str) -> dict[str, object]:
    async for payload in barramento.assinar(topico):
        return payload
    raise AssertionError("sem mensagem")


def test_topico_do_webchat() -> None:
    assert topico_webchat(LOJA, "abc") == f"webchat:{LOJA}:abc"


async def test_barramento_entrega_para_assinante() -> None:
    b = BarramentoEmMemoria()
    tarefa = asyncio.create_task(_primeira(b, "t"))
    await asyncio.sleep(0)
    await b.publicar("t", {"a": 1})
    assert await asyncio.wait_for(tarefa, 1) == {"a": 1}


async def test_barramento_isola_topicos() -> None:
    b = BarramentoEmMemoria()
    tarefa = asyncio.create_task(_primeira(b, "x"))
    await asyncio.sleep(0)
    await b.publicar("y", {"a": 1})
    await b.publicar("x", {"a": 2})
    assert await asyncio.wait_for(tarefa, 1) == {"a": 2}


async def test_adapter_publica_no_topico_da_sessao() -> None:
    b = BarramentoEmMemoria()
    adapter = WebChatAdapter(b)
    tarefa = asyncio.create_task(_primeira(b, topico_webchat(LOJA, "s1")))
    await asyncio.sleep(0)
    await adapter.enviar(
        MensagemSaida(
            loja_id=LOJA,
            canal=Canal.WEBCHAT,
            destinatario="s1",
            tipo=TipoMensagem.TEXTO,
            texto="ola",
            midia_url=None,
        )
    )
    payload = await asyncio.wait_for(tarefa, 1)
    assert payload["tipo"] == "texto"
    assert payload["texto"] == "ola"
    assert payload["midia_url"] is None
    assert isinstance(payload["enviada_em"], str)
