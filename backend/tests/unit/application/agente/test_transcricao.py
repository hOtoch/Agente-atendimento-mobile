"""Transcricao do LLM: serializacao sem perda e repositorio em memoria (so por acrescimo)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

from app.application.agente.transcricao import (
    CursorEntrada,
    RepositorioTranscricaoEmMemoria,
    desserializar_mensagem,
    serializar_mensagem,
)
from app.application.llm import (
    BlocoImagem,
    BlocoTexto,
    ChamadaFerramenta,
    MensagemLLM,
    ResultadoFerramenta,
)

BRUTO = [
    {"type": "thinking", "thinking": "preciso consultar o estoque", "signature": "ZmFrZQ=="},
    {"type": "text", "text": "Vou ver aqui."},
    {"type": "tool_use", "id": "toolu_1", "name": "consultar_estoque", "input": {"modelo": "16"}},
]

MENSAGENS = [
    MensagemLLM("user", [BlocoTexto("oi"), BlocoTexto("quero um iphone")]),
    MensagemLLM("user", [BlocoImagem("image/png", "AAAA")]),
    MensagemLLM("system", [BlocoTexto("ESTADO")]),
    MensagemLLM(
        "assistant",
        [BlocoTexto("Vou ver aqui."), ChamadaFerramenta("toolu_1", "consultar_estoque", {"a": 1})],
        bruto=BRUTO,
    ),
    MensagemLLM(
        "user",
        [ResultadoFerramenta("toolu_1", '{"ok": true}'), ResultadoFerramenta("toolu_2", "x", True)],
    ),
]


def test_serializacao_ida_e_volta_sem_perda_e_e_json_puro() -> None:
    for msg in MENSAGENS:
        dados = serializar_mensagem(msg)
        assert desserializar_mensagem(json.loads(json.dumps(dados))) == msg


def test_bruto_volta_intacto() -> None:
    msg = MENSAGENS[3]
    volta = desserializar_mensagem(json.loads(json.dumps(serializar_mensagem(msg))))
    assert volta.bruto == BRUTO


async def test_memoria_lista_na_ordem_e_so_acrescenta() -> None:
    repo = RepositorioTranscricaoEmMemoria()
    conversa = uuid4()
    assert await repo.listar(conversa) == []
    await repo.acrescentar(conversa, MENSAGENS[:2])
    primeira = await repo.listar(conversa)
    await repo.acrescentar(conversa, MENSAGENS[2:])
    assert await repo.listar(conversa) == MENSAGENS
    assert (await repo.listar(conversa))[:2] == primeira
    assert await repo.listar(uuid4()) == []


async def test_cursor_acompanha_o_acrescimo_e_a_marcacao_avulsa() -> None:
    repo = RepositorioTranscricaoEmMemoria()
    conversa = uuid4()
    assert await repo.consumido_ate(conversa) is None
    c1 = CursorEntrada(datetime(2026, 11, 20, tzinfo=UTC), uuid4())
    await repo.acrescentar(conversa, MENSAGENS[:1], consumido_ate=c1)
    assert await repo.consumido_ate(conversa) == c1
    c2 = CursorEntrada(datetime(2026, 11, 21, tzinfo=UTC), uuid4())
    await repo.marcar_consumidas(conversa, c2)
    assert await repo.consumido_ate(conversa) == c2
    assert await repo.listar(conversa) == MENSAGENS[:1]  # marcar nao mexe na transcricao
