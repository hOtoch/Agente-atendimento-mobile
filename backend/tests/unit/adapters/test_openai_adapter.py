"""OpenAIAdapter (Chat Completions) contra `httpx.MockTransport`: nenhum teste toca a rede."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from app.adapters.outbound.llm.openai_adapter import OpenAIAdapter
from app.application.llm import (
    BlocoImagem,
    BlocoTexto,
    ChamadaFerramenta,
    DefinicaoFerramenta,
    ErroLLM,
    LLMIndisponivel,
    LLMPort,
    LLMRecusou,
    MensagemLLM,
    ResultadoFerramenta,
    UsoTokens,
)

PRINCIPAL = "gpt-4.1-mini"
RESERVA = "gpt-4o-mini"
ROTA = "/v1/chat/completions"

Handler = Callable[[httpx.Request], httpx.Response]


def resposta_ok(
    *,
    content: str | None = "Oi!",
    tool_calls: list[dict[str, Any]] | None = None,
    finish_reason: str = "stop",
    model: str = PRINCIPAL,
    refusal: str | None = None,
    usage: dict[str, Any] | None = None,
) -> httpx.Response:
    mensagem: dict[str, Any] = {"role": "assistant", "content": content, "refusal": refusal}
    if tool_calls is not None:
        mensagem["tool_calls"] = tool_calls
    return httpx.Response(
        200,
        json={
            "id": "chatcmpl-1",
            "object": "chat.completion",
            "model": model,
            "choices": [{"index": 0, "message": mensagem, "finish_reason": finish_reason}],
            "usage": usage
            or {
                "prompt_tokens": 1200,
                "completion_tokens": 30,
                "prompt_tokens_details": {"cached_tokens": 1024},
            },
        },
    )


def chamada_api(id_: str, nome: str, argumentos: str) -> dict[str, Any]:
    return {"id": id_, "type": "function", "function": {"name": nome, "arguments": argumentos}}


class Gravador:
    """Responde em sequencia e guarda os requests."""

    def __init__(self, *respostas: httpx.Response | Exception) -> None:
        self.respostas = list(respostas)
        self.requests: list[httpx.Request] = []

    def __call__(self, req: httpx.Request) -> httpx.Response:
        self.requests.append(req)
        r = self.respostas.pop(0) if len(self.respostas) > 1 else self.respostas[0]
        if isinstance(r, Exception):
            raise r
        return r

    def corpo(self, i: int = -1) -> dict[str, Any]:
        return dict(json.loads(self.requests[i].content))


def sem_instrucao(g: Gravador) -> list[dict[str, Any]]:
    """Mensagens enviadas sem a instrucao fixa da OpenAI (posicao 1, logo depois de `["s"]`)."""
    msgs: list[dict[str, Any]] = g.corpo()["messages"]
    return [msgs[0], *msgs[2:]]


def adaptador(
    handler: Handler,
    *,
    modelo: str = PRINCIPAL,
    reserva: str | None = RESERVA,
    tentativas: int = 2,
    effort: str = "low",
) -> OpenAIAdapter:
    cliente = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://api.openai.test"
    )
    return OpenAIAdapter(
        cliente,
        api_key="sk-teste",
        modelo=modelo,
        modelo_reserva=reserva,
        effort=effort,
        tentativas=tentativas,
        backoff_s=0,
    )


def usuario(texto: str = "Tem iPhone 15?") -> MensagemLLM:
    return MensagemLLM("user", [BlocoTexto(texto)])


FERRAMENTA = DefinicaoFerramenta(
    nome="consultar_estoque",
    descricao="Busca aparelhos no estoque.",
    esquema_json={
        "type": "object",
        "properties": {"modelo": {"type": "string"}},
        "required": ["modelo"],
        "additionalProperties": False,
    },
)


def test_implementa_a_porta() -> None:
    def _aceita(llm: LLMPort) -> None: ...

    _aceita(adaptador(Gravador(resposta_ok())))


# --- request -----------------------------------------------------------------------------


async def test_request_basico_com_sistema_ferramentas_e_autorizacao() -> None:
    g = Gravador(resposta_ok())
    await adaptador(g).responder(
        ["prefixo estavel", "bloco da loja"], [usuario()], [FERRAMENTA], 512
    )

    req = g.requests[0]
    assert req.method == "POST" and req.url.path == ROTA
    assert req.headers["authorization"] == "Bearer sk-teste"
    corpo = g.corpo()
    assert corpo["model"] == PRINCIPAL
    assert corpo["max_completion_tokens"] == 512
    # prefixo estavel primeiro (cache automatico de prefixo da OpenAI)
    assert corpo["messages"][:2] == [
        {"role": "system", "content": "prefixo estavel"},
        {"role": "system", "content": "bloco da loja"},
    ]
    # instrucao fixa so da OpenAI: registrar com ferramentas antes de perguntar (cacheavel)
    assert corpo["messages"][2]["role"] == "system"
    assert "ferramenta" in corpo["messages"][2]["content"]
    assert "PRÓXIMA PERGUNTA" in corpo["messages"][2]["content"]
    assert corpo["messages"][3] == {
        "role": "user",
        "content": [{"type": "text", "text": "Tem iPhone 15?"}],
    }
    assert corpo["tools"] == [
        {
            "type": "function",
            "function": {
                "name": "consultar_estoque",
                "description": "Busca aparelhos no estoque.",
                "parameters": FERRAMENTA.esquema_json,
            },
        }
    ]


async def test_ferramentas_reais_do_agente_respeitam_as_regras_da_openai() -> None:
    from app.application.agente.ferramentas import CatalogoFerramentas

    definicoes = CatalogoFerramentas().definicoes()
    g = Gravador(resposta_ok())
    await adaptador(g).responder(["s"], [usuario()], definicoes)

    tools = g.corpo()["tools"]
    assert len(tools) == len(definicoes) <= 128
    for t in tools:
        funcao = t["function"]
        assert re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", funcao["name"])
        assert funcao["parameters"]["type"] == "object"
        assert "strict" not in funcao


async def test_sem_ferramentas_nao_envia_tools() -> None:
    g = Gravador(resposta_ok())
    await adaptador(g).responder(["s"], [usuario()], [])
    assert "tools" not in g.corpo()


async def test_imagem_vai_como_data_url() -> None:
    g = Gravador(resposta_ok())
    msg = MensagemLLM("user", [BlocoTexto("olha a bateria"), BlocoImagem("image/png", "QUJD")])
    await adaptador(g).responder(["s"], [msg], [])
    assert sem_instrucao(g)[1]["content"] == [
        {"type": "text", "text": "olha a bateria"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,QUJD"}},
    ]


async def test_mensagem_de_sistema_no_meio_da_conversa() -> None:
    g = Gravador(resposta_ok())
    estado = MensagemLLM("system", [BlocoTexto("estado A"), BlocoTexto("estado B")])
    await adaptador(g).responder(["s"], [usuario(), estado], [])
    # vai antes da fala do cliente (ver test_estado_que_segue_a_fala_do_cliente_vai_antes_dela)
    assert sem_instrucao(g)[1] == {"role": "system", "content": "estado A\n\nestado B"}


async def test_estado_que_segue_a_fala_do_cliente_vai_antes_dela() -> None:
    """O orquestrador grava [usuario, estado] a cada turno. Na OpenAI a fala do cliente precisa
    ser a ultima: com o estado depois dela, o modelo segue a "proxima pergunta" (montada antes de
    ler a fala) e ignora o que o cliente acabou de dizer."""
    g = Gravador(resposta_ok())
    estado1 = MensagemLLM("system", [BlocoTexto("estado 1")])
    estado2 = MensagemLLM("system", [BlocoTexto("estado 2")])
    historico = [
        usuario("oi"),
        estado1,
        MensagemLLM("assistant", [BlocoTexto("Oi! Qual aparelho?")]),
        usuario("iPhone 15"),
        estado2,
    ]
    await adaptador(g).responder(["s"], historico, [])
    papeis_e_textos = [
        (m["role"], m["content"] if isinstance(m["content"], str) else m["content"][0]["text"])
        for m in sem_instrucao(g)[1:]
    ]
    assert papeis_e_textos == [
        ("system", "estado 1"),
        ("user", "oi"),
        ("assistant", "Oi! Qual aparelho?"),
        ("system", "estado 2"),
        ("user", "iPhone 15"),
    ]


async def test_estado_nao_separa_chamada_de_ferramenta_do_resultado() -> None:
    g = Gravador(resposta_ok())
    historico = [
        usuario("oi"),
        MensagemLLM("assistant", [ChamadaFerramenta("c", "consultar_estoque", {})]),
        MensagemLLM("user", [ResultadoFerramenta("c", "ok")]),
        MensagemLLM("system", [BlocoTexto("estado")]),
    ]
    await adaptador(g).responder(["s"], historico, [])
    papeis = [m["role"] for m in sem_instrucao(g)[1:]]
    assert papeis == ["user", "assistant", "tool", "system"]


async def test_chamadas_e_resultados_de_ferramenta_no_historico() -> None:
    g = Gravador(resposta_ok())
    assistente = MensagemLLM(
        "assistant",
        [
            BlocoTexto("Vou ver."),
            ChamadaFerramenta("call_1", "consultar_estoque", {"modelo": "15"}),
        ],
        # historico gravado pelo adaptador da Anthropic: o bruto e de outro provedor e e ignorado
        bruto=[{"type": "thinking", "thinking": "x", "signature": "y"}],
    )
    resultados = MensagemLLM(
        "user",
        [
            ResultadoFerramenta("call_1", '{"itens": 2}'),
            ResultadoFerramenta("call_2", "modelo desconhecido", erro=True),
            BlocoTexto("e o 16?"),
        ],
    )
    await adaptador(g).responder(["s"], [usuario(), assistente, resultados], [])

    msgs = sem_instrucao(g)
    assert msgs[2] == {
        "role": "assistant",
        "content": "Vou ver.",
        "tool_calls": [chamada_api("call_1", "consultar_estoque", '{"modelo": "15"}')],
    }
    # os resultados vem logo depois do assistant (exigencia da API); o texto do usuario depois
    assert msgs[3] == {"role": "tool", "tool_call_id": "call_1", "content": '{"itens": 2}'}
    assert msgs[4] == {
        "role": "tool",
        "tool_call_id": "call_2",
        "content": "ERRO: modelo desconhecido",
    }
    assert msgs[5] == {"role": "user", "content": [{"type": "text", "text": "e o 16?"}]}
    assert len(msgs) == 6


async def test_resposta_vazia_gravada_no_historico_vai_com_content_vazio() -> None:
    """Resposta sem texto e sem ferramenta: o orquestrador manda MENSAGEM_LIMITE ao cliente mas
    grava a mensagem vazia. `content: null` sem `tool_calls` e recusado pela API (400) e
    quebraria todos os turnos seguintes da conversa."""
    g = Gravador(resposta_ok())
    vazia = MensagemLLM("assistant", [])
    await adaptador(g).responder(["s"], [usuario(), vazia, usuario("oi?")], [])
    msgs = sem_instrucao(g)
    assert msgs[2] == {"role": "assistant", "content": ""}


async def test_assistente_so_com_ferramenta_vai_com_content_nulo() -> None:
    g = Gravador(resposta_ok())
    assistente = MensagemLLM("assistant", [ChamadaFerramenta("c", "consultar_estoque", {})])
    resultado = MensagemLLM("user", [ResultadoFerramenta("c", "ok")])
    await adaptador(g).responder(["s"], [usuario(), assistente, resultado], [])
    msgs = sem_instrucao(g)
    assert msgs[2]["content"] is None
    assert msgs[3] == {"role": "tool", "tool_call_id": "c", "content": "ok"}
    assert len(msgs) == 4  # nenhuma mensagem `user` vazia depois dos resultados


async def test_modelo_de_raciocinio_recebe_o_effort() -> None:
    g = Gravador(resposta_ok(model="gpt-5-mini"))
    await adaptador(g, modelo="gpt-5-mini", reserva=None).responder(["s"], [usuario()], [])
    assert g.corpo()["reasoning_effort"] == "low"


async def test_gpt_6_e_de_raciocinio_e_recebe_o_effort() -> None:
    g = Gravador(resposta_ok(model="gpt-6-luna"))
    await adaptador(g, modelo="gpt-6-luna", reserva=None).responder(["s"], [usuario()], [])
    assert g.corpo()["reasoning_effort"] == "low"


async def test_gpt_6_com_ferramentas_usa_effort_none() -> None:
    """Na Chat Completions o gpt-6 recusa (400) reasoning_effort com ferramentas, exceto 'none'."""
    g = Gravador(resposta_ok(model="gpt-6-luna"))
    await adaptador(g, modelo="gpt-6-luna", reserva=None).responder(
        ["s"], [usuario()], [FERRAMENTA]
    )
    assert g.corpo()["reasoning_effort"] == "none"


async def test_gpt_5_com_ferramentas_mantem_o_effort_configurado() -> None:
    g = Gravador(resposta_ok(model="gpt-5-mini"))
    await adaptador(g, modelo="gpt-5-mini", reserva=None).responder(
        ["s"], [usuario()], [FERRAMENTA]
    )
    assert g.corpo()["reasoning_effort"] == "low"


async def test_modelo_sem_raciocinio_nao_recebe_effort() -> None:
    g = Gravador(resposta_ok())
    await adaptador(g).responder(["s"], [usuario()], [])
    assert "reasoning_effort" not in g.corpo()


# --- resposta ----------------------------------------------------------------------------


async def test_resposta_de_texto() -> None:
    r = await adaptador(Gravador(resposta_ok(content="Temos sim!"))).responder(
        ["s"], [usuario()], []
    )
    assert r.texto == "Temos sim!"
    assert r.chamadas == []
    assert r.motivo_parada == "end_turn"
    assert r.modelo_usado == PRINCIPAL
    assert r.mensagem_assistente == MensagemLLM("assistant", [BlocoTexto("Temos sim!")])


async def test_resposta_com_ferramentas() -> None:
    resposta = resposta_ok(
        content=None,
        finish_reason="tool_calls",
        tool_calls=[
            chamada_api("call_9", "consultar_estoque", '{"modelo": "iPhone 15"}'),
            chamada_api("call_10", "registrar", "{nao e json"),
        ],
    )
    r = await adaptador(Gravador(resposta)).responder(["s"], [usuario()], [FERRAMENTA])

    assert r.texto == ""
    assert r.motivo_parada == "tool_use"
    assert r.chamadas == [
        ChamadaFerramenta("call_9", "consultar_estoque", {"modelo": "iPhone 15"}),
        # argumento invalido vira entrada vazia: a validacao da ferramenta devolve o erro ao modelo
        ChamadaFerramenta("call_10", "registrar", {}),
    ]
    assert r.mensagem_assistente.blocos == r.chamadas
    assert r.mensagem_assistente.bruto is None


async def test_corte_por_tamanho_vira_max_tokens() -> None:
    r = await adaptador(Gravador(resposta_ok(finish_reason="length"))).responder(
        ["s"], [usuario()], []
    )
    assert r.motivo_parada == "max_tokens"


async def test_uso_separa_o_prompt_cacheado() -> None:
    r = await adaptador(Gravador(resposta_ok())).responder(["s"], [usuario()], [])
    assert r.uso == UsoTokens(PRINCIPAL, entrada=176, saida=30, cache_leitura=1024, cache_escrita=0)


async def test_modelo_reportado_e_o_configurado_sem_a_data_do_snapshot() -> None:
    """A API devolve `gpt-4.1-mini-2025-04-14`; a tabela de precos e a telemetria usam o alias."""
    resposta = resposta_ok(model="gpt-4.1-mini-2025-04-14")
    r = await adaptador(Gravador(resposta)).responder(["s"], [usuario()], [])
    assert r.modelo_usado == PRINCIPAL
    assert r.uso.modelo == PRINCIPAL


async def test_uso_sem_detalhes_de_cache() -> None:
    resposta = resposta_ok(usage={"prompt_tokens": 50, "completion_tokens": 5})
    r = await adaptador(Gravador(resposta)).responder(["s"], [usuario()], [])
    assert r.uso == UsoTokens(PRINCIPAL, entrada=50, saida=5, cache_leitura=0, cache_escrita=0)


async def test_recusa_levanta_llm_recusou() -> None:
    resposta = resposta_ok(content=None, refusal="Nao posso ajudar com isso.")
    with pytest.raises(LLMRecusou) as exc:
        await adaptador(Gravador(resposta)).responder(["s"], [usuario()], [])
    assert exc.value.modelo == PRINCIPAL


async def test_filtro_de_conteudo_levanta_llm_recusou() -> None:
    resposta = resposta_ok(content=None, finish_reason="content_filter")
    with pytest.raises(LLMRecusou):
        await adaptador(Gravador(resposta)).responder(["s"], [usuario()], [])


# --- erros, retry e reserva --------------------------------------------------------------


async def test_429_tenta_de_novo_no_mesmo_modelo() -> None:
    g = Gravador(httpx.Response(429, json={"error": {"message": "rate"}}), resposta_ok())
    r = await adaptador(g).responder(["s"], [usuario()], [])
    assert r.texto == "Oi!"
    assert [json.loads(q.content)["model"] for q in g.requests] == [PRINCIPAL, PRINCIPAL]


async def test_5xx_esgotado_cai_no_modelo_reserva() -> None:
    erro = httpx.Response(500, json={"error": {"message": "boom"}})
    g = Gravador(erro, erro, resposta_ok(model=RESERVA))
    r = await adaptador(g).responder(["s"], [usuario()], [])
    assert r.modelo_usado == RESERVA
    assert [json.loads(q.content)["model"] for q in g.requests] == [PRINCIPAL, PRINCIPAL, RESERVA]


async def test_rede_fora_conta_como_transitorio() -> None:
    g = Gravador(httpx.ConnectError("sem rede"), resposta_ok())
    r = await adaptador(g, tentativas=2).responder(["s"], [usuario()], [])
    assert r.texto == "Oi!"


async def test_tudo_falhando_levanta_indisponivel_com_status() -> None:
    g = Gravador(httpx.Response(503, json={"error": {"message": "fora"}}))
    with pytest.raises(LLMIndisponivel) as exc:
        await adaptador(g).responder(["s"], [usuario()], [])
    assert exc.value.status == 503
    assert exc.value.modelo == RESERVA
    assert len(g.requests) == 4  # 2 tentativas x 2 modelos


async def test_erro_4xx_nao_tenta_de_novo_e_nao_vaza_a_chave() -> None:
    g = Gravador(httpx.Response(400, json={"error": {"message": "parametro invalido"}}))
    with pytest.raises(ErroLLM) as exc:
        await adaptador(g).responder(["s"], [usuario()], [])
    assert not isinstance(exc.value, LLMIndisponivel)
    assert exc.value.status == 400
    assert "parametro invalido" in str(exc.value)
    assert "sk-teste" not in str(exc.value)
    assert len(g.requests) == 1


async def test_resposta_fora_do_formato_vira_erro_llm() -> None:
    g = Gravador(httpx.Response(200, json={"inesperado": True}))
    with pytest.raises(ErroLLM, match="inesperada"):
        await adaptador(g).responder(["s"], [usuario()], [])


def test_tentativas_precisa_ser_positivo() -> None:
    with pytest.raises(ValueError, match="tentativas"):
        adaptador(Gravador(resposta_ok()), tentativas=0)
