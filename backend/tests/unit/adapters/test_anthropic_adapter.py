"""AnthropicAdapter contra HTTP simulado.

O SDK `anthropic` 2.x roda sobre `httpx2` (nao `httpx`), e o `respx` so intercepta o `httpx`.
Por isso o HTTP e simulado com `httpx2.MockTransport` injetado no cliente: o SDK real
serializa o request e interpreta a resposta; nenhuma chamada de rede acontece.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any

import anthropic
import httpx2
import pytest

from app.adapters.outbound.llm.anthropic_adapter import AnthropicAdapter
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
from app.infra.llm import criar_llm
from app.infra.settings import Settings

SONNET = "claude-sonnet-5-5"
HAIKU = "claude-haiku-5-5"
URL = "https://api.anthropic.com/v1/messages"


def resposta_ok(
    content: list[dict[str, Any]] | None = None,
    stop_reason: str = "end_turn",
    model: str = SONNET,
    usage: dict[str, int] | None = None,
    **extra: Any,
) -> httpx2.Response:
    corpo = {
        "id": "msg_1",
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": content if content is not None else [{"type": "text", "text": "ola"}],
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": usage or {"input_tokens": 12, "output_tokens": 7},
        **extra,
    }
    return httpx2.Response(200, json=corpo)


def resposta_erro(status: int, tipo: str = "api_error") -> httpx2.Response:
    return httpx2.Response(
        status, json={"type": "error", "error": {"type": tipo, "message": "falhou"}}
    )


class ApiFalsa:
    """Responde em sequencia e guarda os requests recebidos."""

    def __init__(self, *respostas: httpx2.Response | Exception) -> None:
        self._respostas = list(respostas)
        self.requests: list[httpx2.Request] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        item = self._respostas.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def corpo(self, i: int = 0) -> dict[str, Any]:
        corpo: dict[str, Any] = json.loads(self.requests[i].content)
        return corpo

    @property
    def modelos(self) -> list[str]:
        return [json.loads(r.content)["model"] for r in self.requests]


def montar(
    api: ApiFalsa,
    modelo: str = SONNET,
    reserva: str | None = HAIKU,
    **kwargs: Any,
) -> AnthropicAdapter:
    cliente = anthropic.AsyncAnthropic(
        api_key="chave-de-teste",
        max_retries=0,
        http_client=anthropic.DefaultAsyncHttpxClient(transport=httpx2.MockTransport(api)),
    )
    kwargs.setdefault("backoff_s", 0.0)
    return AnthropicAdapter(cliente, modelo, reserva, **kwargs)


def usuario(texto: str = "oi") -> MensagemLLM:
    return MensagemLLM("user", [BlocoTexto(texto)])


FERRAMENTAS = [
    DefinicaoFerramenta(
        "buscar_estoque",
        "Busca aparelhos",
        {
            "type": "object",
            "properties": {"modelo": {"type": "string"}},
            "required": ["modelo"],
            "additionalProperties": False,
        },
    ),
    DefinicaoFerramenta("avaliar_troca", "Avalia troca", {"type": "object"}),
]


# --- corpo do request -----------------------------------------------------------------


async def test_corpo_basico_na_sonnet() -> None:
    api = ApiFalsa(resposta_ok())
    await montar(api).responder(["estavel"], [usuario("bom dia")], [])

    req = api.requests[0]
    assert str(req.url) == URL
    corpo = api.corpo()
    assert corpo["model"] == SONNET
    assert corpo["max_tokens"] == 1024
    assert corpo["output_config"] == {"effort": "low"}
    assert corpo["messages"] == [{"role": "user", "content": [{"type": "text", "text": "bom dia"}]}]


async def test_nao_envia_parametros_que_dao_400_nos_modelos_5_5() -> None:
    api = ApiFalsa(resposta_ok(), resposta_ok(model=HAIKU))
    await montar(api, reserva=None).responder(["s"], [usuario()], FERRAMENTAS)
    await montar(api, modelo=HAIKU, reserva=None).responder(["s"], [usuario()], FERRAMENTAS)

    for i in range(2):
        corpo = api.corpo(i)
        for proibido in ("temperature", "top_p", "top_k", "tool_choice", "thinking"):
            assert proibido not in corpo
        assert corpo["messages"][-1]["role"] != "assistant"  # sem prefill


async def test_cache_control_no_sistema_estavel_e_na_ultima_ferramenta() -> None:
    api = ApiFalsa(resposta_ok())
    await montar(api).responder(["prefixo estavel", "estado volatil"], [usuario()], FERRAMENTAS)

    corpo = api.corpo()
    assert corpo["system"] == [
        {"type": "text", "text": "prefixo estavel", "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": "estado volatil"},
    ]
    assert "cache_control" not in corpo["tools"][0]
    assert corpo["tools"][1]["cache_control"] == {"type": "ephemeral"}


async def test_ferramentas_sao_estritas_e_usam_input_schema() -> None:
    api = ApiFalsa(resposta_ok())
    await montar(api).responder([], [usuario()], FERRAMENTAS)

    t = api.corpo()["tools"][0]
    assert t["name"] == "buscar_estoque"
    assert t["description"] == "Busca aparelhos"
    assert t["strict"] is True
    assert t["input_schema"] == FERRAMENTAS[0].esquema_json


async def test_ferramenta_nao_estrita_omite_strict() -> None:
    api = ApiFalsa(resposta_ok())
    solta = DefinicaoFerramenta("x", "d", {"type": "object"}, estrita=False)
    await montar(api).responder([], [usuario()], [solta])
    assert "strict" not in api.corpo()["tools"][0]


async def test_sem_sistema_e_sem_ferramentas_omite_os_campos() -> None:
    api = ApiFalsa(resposta_ok())
    await montar(api).responder([], [usuario()], [])
    corpo = api.corpo()
    assert "system" not in corpo
    assert "tools" not in corpo


async def test_fallback_de_recusa_so_na_sonnet_via_beta() -> None:
    api = ApiFalsa(resposta_ok(), resposta_ok(model=HAIKU))
    await montar(api, reserva=None).responder(["s"], [usuario()], [])
    await montar(api, modelo=HAIKU, reserva=None).responder(["s"], [usuario()], [])

    assert api.corpo(0)["fallbacks"] == "default"
    assert "server-side-fallback-2026-07-01" in api.requests[0].headers["anthropic-beta"]
    assert "fallbacks" not in api.corpo(1)
    assert "anthropic-beta" not in api.requests[1].headers


async def test_mensagem_de_sistema_no_meio_vai_como_role_system() -> None:
    api = ApiFalsa(resposta_ok())
    msgs = [usuario("quero um iphone"), MensagemLLM("system", [BlocoTexto("Ficha: modelo=16")])]
    await montar(api).responder(["s"], msgs, [])

    assert api.corpo()["messages"] == [
        {"role": "user", "content": [{"type": "text", "text": "quero um iphone"}]},
        {"role": "system", "content": "Ficha: modelo=16"},
    ]


async def test_imagem_e_resultado_de_ferramenta_sao_serializados() -> None:
    api = ApiFalsa(resposta_ok())
    msgs = [
        MensagemLLM("user", [BlocoImagem("image/png", "QUJD"), BlocoTexto("e este?")]),
        MensagemLLM(
            "assistant", [ChamadaFerramenta("toolu_1", "buscar_estoque", {"modelo": "16"})]
        ),
        MensagemLLM(
            "user",
            [
                ResultadoFerramenta("toolu_1", "2 unidades"),
                ResultadoFerramenta("toolu_2", "falhou", erro=True),
            ],
        ),
    ]
    await montar(api).responder([], msgs, [])

    m = api.corpo()["messages"]
    assert m[0]["content"][0] == {
        "type": "image",
        "source": {"type": "base64", "media_type": "image/png", "data": "QUJD"},
    }
    assert m[1] == {
        "role": "assistant",
        "content": [
            {
                "type": "tool_use",
                "id": "toolu_1",
                "name": "buscar_estoque",
                "input": {"modelo": "16"},
            }
        ],
    }
    assert m[2]["content"] == [
        {"type": "tool_result", "tool_use_id": "toolu_1", "content": "2 unidades"},
        {"type": "tool_result", "tool_use_id": "toolu_2", "content": "falhou", "is_error": True},
    ]


# --- resposta ------------------------------------------------------------------------


async def test_texto_uso_e_modelo_da_resposta() -> None:
    api = ApiFalsa(
        resposta_ok(
            [{"type": "text", "text": "Tenho sim."}, {"type": "text", "text": " Quer ver?"}],
            usage={
                "input_tokens": 20,
                "output_tokens": 9,
                "cache_read_input_tokens": 500,
                "cache_creation_input_tokens": 40,
            },
        )
    )
    r = await montar(api).responder(["s"], [usuario()], [])

    assert r.texto == "Tenho sim. Quer ver?"
    assert r.chamadas == []
    assert r.motivo_parada == "end_turn"
    assert r.modelo_usado == SONNET
    assert r.uso == UsoTokens(SONNET, entrada=20, saida=9, cache_leitura=500, cache_escrita=40)
    assert r.mensagem_assistente.papel == "assistant"


async def test_tool_use_vira_chamada_de_ferramenta() -> None:
    api = ApiFalsa(
        resposta_ok(
            [
                {"type": "text", "text": "Vou conferir."},
                {
                    "type": "tool_use",
                    "id": "toolu_9",
                    "name": "buscar_estoque",
                    "input": {"modelo": "iPhone 16"},
                },
            ],
            stop_reason="tool_use",
        )
    )
    r = await montar(api).responder(["s"], [usuario()], FERRAMENTAS)

    assert r.motivo_parada == "tool_use"
    assert r.chamadas == [ChamadaFerramenta("toolu_9", "buscar_estoque", {"modelo": "iPhone 16"})]
    assert r.texto == "Vou conferir."
    assert r.mensagem_assistente.blocos == [BlocoTexto("Vou conferir."), *r.chamadas]


async def test_bruto_do_assistente_e_reenviado_intacto_com_thinking() -> None:
    content = [
        {"type": "thinking", "thinking": "", "signature": "assinatura-opaca=="},
        {"type": "text", "text": "Vou conferir."},
        {"type": "tool_use", "id": "toolu_1", "name": "buscar_estoque", "input": {"modelo": "16"}},
    ]
    api = ApiFalsa(resposta_ok(content, stop_reason="tool_use"), resposta_ok())
    adapter = montar(api)
    r1 = await adapter.responder(["s"], [usuario()], FERRAMENTAS)

    assert r1.mensagem_assistente.bruto == content

    historico = [
        usuario(),
        r1.mensagem_assistente,
        MensagemLLM("user", [ResultadoFerramenta("toolu_1", "ok")]),
    ]
    await adapter.responder(["s"], historico, FERRAMENTAS)

    reenviado = api.corpo(1)["messages"][1]
    assert reenviado == {"role": "assistant", "content": content}


async def test_bruto_descarta_so_o_que_veio_antes_do_bloco_fallback() -> None:
    content = [
        {"type": "thinking", "thinking": "", "signature": "velha"},
        {"type": "fallback", "from": {"model": SONNET}, "to": {"model": "claude-sonnet-5"}},
        {"type": "thinking", "thinking": "", "signature": "nova"},
        {"type": "text", "text": "resposta"},
    ]
    api = ApiFalsa(resposta_ok(content), resposta_ok())
    adapter = montar(api)
    r1 = await adapter.responder(["s"], [usuario()], [])
    await adapter.responder(["s"], [usuario(), r1.mensagem_assistente, usuario("e ai")], [])

    enviado = api.corpo(1)["messages"][1]["content"]
    assert [b["type"] for b in enviado] == ["fallback", "thinking", "text"]
    assert enviado[1]["signature"] == "nova"


async def test_uso_acumulado_por_conversa() -> None:
    api = ApiFalsa(
        resposta_ok(usage={"input_tokens": 10, "output_tokens": 5, "cache_read_input_tokens": 100}),
        resposta_ok(usage={"input_tokens": 3, "output_tokens": 2, "cache_read_input_tokens": 120}),
    )
    adapter = montar(api)
    r1 = await adapter.responder(["s"], [usuario()], [])
    r2 = await adapter.responder(["s"], [usuario()], [])
    assert r1.uso + r2.uso == UsoTokens(
        SONNET, entrada=13, saida=7, cache_leitura=220, cache_escrita=0
    )


async def test_registra_o_uso_em_log(caplog: pytest.LogCaptureFixture) -> None:
    api = ApiFalsa(resposta_ok(usage={"input_tokens": 10, "output_tokens": 5}))
    with caplog.at_level(logging.INFO, logger="app.adapters.outbound.llm.anthropic_adapter"):
        await montar(api).responder(["s"], [usuario()], [])
    texto = " ".join(r.getMessage() for r in caplog.records)
    assert SONNET in texto
    assert "entrada=10" in texto
    assert "saida=5" in texto


# --- erros, retry e modelo reserva --------------------------------------------------------


async def test_529_esgota_tentativas_e_cai_no_modelo_reserva() -> None:
    api = ApiFalsa(
        resposta_erro(529, "overloaded_error"),
        resposta_erro(529, "overloaded_error"),
        resposta_ok(model=HAIKU),
    )
    r = await montar(api, tentativas=2).responder(["s"], [usuario()], FERRAMENTAS)

    assert api.modelos == [SONNET, SONNET, HAIKU]
    assert r.modelo_usado == HAIKU
    assert r.uso.modelo == HAIKU
    assert "fallbacks" not in api.corpo(2)  # Haiku nao tem fallback de recusa


async def test_429_com_retry_no_mesmo_modelo() -> None:
    api = ApiFalsa(resposta_erro(429, "rate_limit_error"), resposta_ok())
    r = await montar(api, tentativas=2).responder(["s"], [usuario()], [])
    assert api.modelos == [SONNET, SONNET]
    assert r.modelo_usado == SONNET


@pytest.mark.parametrize(
    "falha",
    [
        httpx2.ConnectError("sem rede"),
        httpx2.ReadTimeout("lento"),
        resposta_erro(500),
    ],
)
async def test_rede_timeout_e_5xx_tambem_tentam_de_novo(falha: Exception | httpx2.Response) -> None:
    api = ApiFalsa(falha, resposta_ok())
    r = await montar(api, tentativas=2).responder(["s"], [usuario()], [])
    assert r.texto == "ola"
    assert api.modelos == [SONNET, SONNET]


async def test_tudo_falhando_levanta_llm_indisponivel() -> None:
    api = ApiFalsa(*[resposta_erro(529, "overloaded_error")] * 4)
    with pytest.raises(LLMIndisponivel):
        await montar(api, tentativas=2).responder(["s"], [usuario()], [])
    assert api.modelos == [SONNET, SONNET, HAIKU, HAIKU]


async def test_sem_modelo_reserva_levanta_llm_indisponivel_apos_as_tentativas() -> None:
    api = ApiFalsa(httpx2.ConnectError("x"), httpx2.ConnectError("y"))
    with pytest.raises(LLMIndisponivel):
        await montar(api, reserva=None, tentativas=2).responder(["s"], [usuario()], [])
    assert len(api.requests) == 2


async def test_bad_request_nao_tem_retry_nem_reserva() -> None:
    api = ApiFalsa(resposta_erro(400, "invalid_request_error"))
    with pytest.raises(ErroLLM) as exc:
        await montar(api, tentativas=3).responder(["s"], [usuario()], [])
    assert not isinstance(exc.value, LLMIndisponivel | LLMRecusou)
    assert len(api.requests) == 1


async def test_erro_de_autenticacao_nao_tem_retry() -> None:
    api = ApiFalsa(resposta_erro(401, "authentication_error"))
    with pytest.raises(ErroLLM) as exc:
        await montar(api).responder(["s"], [usuario()], [])
    assert not isinstance(exc.value, LLMIndisponivel)
    assert len(api.requests) == 1


async def test_recusa_final_levanta_llm_recusou_com_a_categoria() -> None:
    api = ApiFalsa(
        resposta_ok(
            [],
            stop_reason="refusal",
            stop_details={"type": "refusal", "category": "cyber", "explanation": "x"},
        )
    )
    with pytest.raises(LLMRecusou) as exc:
        await montar(api).responder(["s"], [usuario()], [])
    assert exc.value.categoria == "cyber"
    assert api.corpo()["fallbacks"] == "default"
    assert len(api.requests) == 1  # recusa nao dispara retry nem reserva


async def test_recusa_sem_detalhes_tem_categoria_none() -> None:
    api = ApiFalsa(resposta_ok([], stop_reason="refusal"))
    with pytest.raises(LLMRecusou) as exc:
        await montar(api, modelo=HAIKU, reserva=None).responder(["s"], [usuario()], [])
    assert exc.value.categoria is None


# --- fabrica ---------------------------------------------------------------------------


def test_fabrica_monta_o_adaptador_com_os_modelos_do_settings() -> None:
    s = Settings(
        _env_file=None,  # type: ignore[call-arg]
        anthropic_api_key="chave",
        llm_model=SONNET,
        llm_fallback_model=HAIKU,
        llm_effort="medium",
    )
    llm: LLMPort = criar_llm(s)
    assert isinstance(llm, AnthropicAdapter)
    assert (llm.modelo, llm.modelo_reserva) == (SONNET, HAIKU)


async def test_fabrica_sem_chave_so_falha_quando_usada() -> None:
    s = Settings(_env_file=None, anthropic_api_key=None)  # type: ignore[call-arg]
    llm = criar_llm(s)  # nao levanta
    with pytest.raises(ErroLLM, match="ANTHROPIC_API_KEY"):
        await llm.responder(["s"], [usuario()], [])


def test_fabrica_ignora_reserva_vazia_ou_igual_ao_principal() -> None:
    chamadas: list[Callable[[], Any]] = []
    for reserva in ("", SONNET):
        s = Settings(
            _env_file=None,  # type: ignore[call-arg]
            anthropic_api_key="k",
            llm_model=SONNET,
            llm_fallback_model=reserva,
        )
        llm = criar_llm(s)
        assert isinstance(llm, AnthropicAdapter)
        chamadas.append(lambda llm=llm: llm.modelo_reserva)  # type: ignore[misc]
    assert [c() for c in chamadas] == [None, None]
