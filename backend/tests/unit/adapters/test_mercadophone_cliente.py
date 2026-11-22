"""Cliente MCP do Mercado Phone: transporte, SSE/JSON, paginacao, erros, allowlist, mascara.

Tudo sobre `httpx.MockTransport` com respostas sinteticas: nenhuma chamada ao servico real.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any
from urllib.parse import parse_qs

import httpx
import pytest

from app.adapters.outbound.mercadophone.cliente import (
    FERRAMENTAS_PERMITIDAS,
    ClienteMercadoPhone,
    ErroMercadoPhone,
    FerramentaNaoPermitida,
    MercadoPhoneCredencialInvalida,
    MercadoPhoneIndisponivel,
    MercadoPhoneLimiteExcedido,
    MercadoPhoneUsoIndevido,
)
from app.application.estoque import EstoqueIndisponivel
from app.application.relogio import RelogioFalso

URL = "https://mp.exemplo.test/mcp/platform/"
CHAVE = "chave-secreta-xyz-123"

Resposta = Callable[[dict[str, Any], httpx.Request], httpx.Response]


def sse(corpo: dict[str, Any]) -> httpx.Response:
    return httpx.Response(
        200,
        headers={"content-type": "text/event-stream"},
        text=f"event: message\ndata: {json.dumps(corpo)}\n\n",
    )


def resultado_tool(payload: Any, req_id: int, *, erro: bool = False) -> dict[str, Any]:
    resultado: dict[str, Any] = {"content": [{"type": "text", "text": json.dumps(payload)}]}
    if erro:
        resultado["isError"] = True
    return {"jsonrpc": "2.0", "id": req_id, "result": resultado}


class Servidor:
    """Servidor MCP falso: registra as requisicoes e responde `tools/call` via `tools`."""

    def __init__(
        self,
        tools: dict[str, Resposta | Any] | None = None,
        *,
        json_simples: bool = False,
        session_id: str | None = None,
    ) -> None:
        self.tools = tools or {}
        self.json_simples = json_simples
        self.session_id = session_id
        self.requisicoes: list[httpx.Request] = []
        self.corpos: list[dict[str, Any]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requisicoes.append(request)
        corpo = json.loads(request.content)
        self.corpos.append(corpo)
        metodo = corpo["method"]
        if metodo == "notifications/initialized":
            return httpx.Response(202)
        if metodo == "initialize":
            headers = {"Mcp-Session-Id": self.session_id} if self.session_id else {}
            msg = {
                "jsonrpc": "2.0",
                "id": corpo["id"],
                "result": {"protocolVersion": "2025-06-18", "capabilities": {}},
            }
            resposta = sse(msg)
            resposta.headers.update(headers)
            return resposta
        assert metodo == "tools/call"
        nome = corpo["params"]["name"]
        gerador = self.tools[nome]
        saida = gerador(corpo, request) if callable(gerador) else gerador
        if isinstance(saida, httpx.Response):
            return saida
        msg = resultado_tool(saida, corpo["id"])
        if self.json_simples:
            return httpx.Response(200, json=msg)
        return sse(msg)

    @property
    def chamadas_tool(self) -> list[dict[str, Any]]:
        return [c for c in self.corpos if c["method"] == "tools/call"]


def montar(
    servidor: Callable[[httpx.Request], httpx.Response],
    *,
    chave: str | None = CHAVE,
    relogio: RelogioFalso | None = None,
    **kw: Any,
) -> tuple[ClienteMercadoPhone, RelogioFalso]:
    relogio = relogio or RelogioFalso()
    http = httpx.AsyncClient(transport=httpx.MockTransport(servidor))
    return ClienteMercadoPhone(http, URL, chave, relogio=relogio, **kw), relogio


def erro_tool(
    codigo: str, status: int = 422, mensagem: str = "falhou", **extra: Any
) -> Callable[[dict[str, Any], httpx.Request], httpx.Response]:
    def _resp(corpo: dict[str, Any], _req: httpx.Request) -> httpx.Response:
        payload = {"error": mensagem, "status": status, "code": codigo, "hint": "dica", **extra}
        return sse(resultado_tool(payload, corpo["id"], erro=True))

    return _resp


# --- protocolo -------------------------------------------------------------------------------


async def test_initialize_preguicoso_roda_uma_vez_e_envia_notificacao() -> None:
    srv = Servidor({"list_brands": {"total": 0, "items": [], "page": 1, "limit": 300}})
    cliente, _ = montar(srv)
    assert srv.requisicoes == []  # nada na construcao

    await cliente.chamar("list_brands", {})
    await cliente.chamar("list_brands", {})

    metodos = [c["method"] for c in srv.corpos]
    assert metodos == ["initialize", "notifications/initialized", "tools/call", "tools/call"]
    init = srv.corpos[0]
    assert init["jsonrpc"] == "2.0"
    assert init["params"]["protocolVersion"] == "2025-06-18"
    assert "clientInfo" in init["params"]
    assert "id" not in srv.corpos[1]  # notificacao nao tem id


async def test_headers_e_chave_na_query() -> None:
    srv = Servidor({"list_brands": {"total": 0, "items": [], "page": 1, "limit": 300}})
    cliente, _ = montar(srv)

    await cliente.chamar("list_brands", {})

    for req in srv.requisicoes:
        assert req.method == "POST"
        assert req.headers["content-type"] == "application/json"
        assert req.headers["accept"] == "application/json, text/event-stream"
        assert req.headers["mcp-protocol-version"] == "2025-06-18"
        assert parse_qs(req.url.query.decode())["key"] == [CHAVE]
        assert req.url.path == "/mcp/platform/"


async def test_sem_chave_nao_manda_query_key() -> None:
    srv = Servidor({"list_brands": {"total": 0, "items": [], "page": 1, "limit": 300}})
    cliente, _ = montar(srv, chave=None)

    await cliente.chamar("list_brands", {})

    assert all(b"key" not in r.url.query for r in srv.requisicoes)


async def test_reenvia_session_id_quando_o_servidor_devolve() -> None:
    srv = Servidor(
        {"list_brands": {"total": 0, "items": [], "page": 1, "limit": 300}}, session_id="sess-9"
    )
    cliente, _ = montar(srv)

    await cliente.chamar("list_brands", {})

    assert "mcp-session-id" not in srv.requisicoes[0].headers
    assert srv.requisicoes[1].headers["mcp-session-id"] == "sess-9"
    assert srv.requisicoes[2].headers["mcp-session-id"] == "sess-9"


async def test_falha_no_initialize_tenta_de_novo_na_proxima_chamada() -> None:
    tentativas = {"n": 0}
    base = Servidor({"list_brands": {"total": 0, "items": [], "page": 1, "limit": 300}})

    def handler(request: httpx.Request) -> httpx.Response:
        corpo = json.loads(request.content)
        if corpo["method"] == "initialize":
            tentativas["n"] += 1
            if tentativas["n"] == 1:
                return httpx.Response(503)
        return base(request)

    cliente, _ = montar(handler)

    with pytest.raises(MercadoPhoneIndisponivel):
        await cliente.chamar("list_brands", {})
    resultado = await cliente.chamar("list_brands", {})

    assert resultado["total"] == 0
    assert tentativas["n"] == 2


async def test_chamar_envia_nome_e_argumentos() -> None:
    srv = Servidor({"list_inventory": {"total": 0, "items": [], "page": 1, "limit": 5}})
    cliente, _ = montar(srv)

    await cliente.chamar("list_inventory", {"limit": 5, "search": "iphone"})

    chamada = srv.chamadas_tool[0]
    assert chamada["params"] == {
        "name": "list_inventory",
        "arguments": {"limit": 5, "search": "iphone"},
    }


# --- formatos de resposta ---------------------------------------------------------------------


async def test_aceita_resposta_sse() -> None:
    srv = Servidor({"list_brands": {"total": 1, "items": [{"id": 1, "name": "Apple"}]}})
    cliente, _ = montar(srv)

    resultado = await cliente.chamar("list_brands", {})

    assert resultado == {"total": 1, "items": [{"id": 1, "name": "Apple"}]}


async def test_aceita_resposta_json_simples() -> None:
    srv = Servidor({"list_brands": {"total": 1, "items": [{"id": 1}]}}, json_simples=True)
    cliente, _ = montar(srv)

    resultado = await cliente.chamar("list_brands", {})

    assert resultado["items"] == [{"id": 1}]


async def test_sse_com_varios_eventos_pega_o_data_do_id_da_requisicao() -> None:
    def handler(corpo: dict[str, Any], _req: httpx.Request) -> httpx.Response:
        outro = {"jsonrpc": "2.0", "method": "notifications/message", "params": {"x": 1}}
        resposta = resultado_tool({"total": 7, "items": []}, corpo["id"])
        texto = (
            f": keep-alive\n\nevent: message\ndata: {json.dumps(outro)}\n\n"
            f"event: message\ndata: {json.dumps(resposta)}\n\n"
        )
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, text=texto)

    cliente, _ = montar(Servidor({"list_brands": handler}))

    assert (await cliente.chamar("list_brands", {}))["total"] == 7


async def test_resposta_lista_vira_dict_com_items() -> None:
    srv = Servidor({"list_my_stores": [{"id": 1}, {"id": 2}]})
    cliente, _ = montar(srv)

    resultado = await cliente.chamar("list_my_stores", {})

    assert resultado == {"items": [{"id": 1}, {"id": 2}], "total": 2}


async def test_corpo_ilegivel_vira_erro_tipado() -> None:
    def handler(_c: dict[str, Any], _r: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, text="lixo")

    cliente, _ = montar(Servidor({"list_brands": handler}))

    with pytest.raises(ErroMercadoPhone):
        await cliente.chamar("list_brands", {})


# --- paginacao --------------------------------------------------------------------------------


def servidor_paginado(total: int) -> Servidor:
    def handler(corpo: dict[str, Any], _req: httpx.Request) -> dict[str, Any]:
        args = corpo["params"]["arguments"]
        limit, page = args["limit"], args["page"]
        if limit > 300:
            return {"error": "limit invalido", "status": 422, "code": "validation_error"}
        inicio = (page - 1) * limit
        itens = [{"id": i} for i in range(inicio, min(inicio + limit, total))]
        return {"total": total, "items": itens, "page": page, "limit": limit}

    return Servidor({"list_inventory": handler})


async def test_paginar_junta_todas_as_paginas() -> None:
    srv = servidor_paginado(650)
    cliente, _ = montar(srv)

    itens = await cliente.paginar("list_inventory", {"store_id": 3})

    assert [i["id"] for i in itens] == list(range(650))
    chamadas = srv.chamadas_tool
    assert [c["params"]["arguments"]["page"] for c in chamadas] == [1, 2, 3]
    assert all(c["params"]["arguments"]["limit"] == 300 for c in chamadas)
    assert all(c["params"]["arguments"]["store_id"] == 3 for c in chamadas)


async def test_paginar_para_ao_alcancar_o_total_sem_pedir_pagina_extra() -> None:
    srv = servidor_paginado(600)
    cliente, _ = montar(srv)

    itens = await cliente.paginar("list_inventory", {})

    assert len(itens) == 600
    assert len(srv.chamadas_tool) == 2


async def test_paginar_nunca_pede_limit_acima_de_300() -> None:
    srv = servidor_paginado(10)
    cliente, _ = montar(srv)

    itens = await cliente.paginar("list_inventory", {"limit": 5000})

    assert len(itens) == 10
    assert all(c["params"]["arguments"]["limit"] <= 300 for c in srv.chamadas_tool)


async def test_paginar_respeita_limit_menor_pedido() -> None:
    srv = servidor_paginado(25)
    cliente, _ = montar(srv)

    itens = await cliente.paginar("list_inventory", {"limit": 10})

    assert len(itens) == 25
    assert [c["params"]["arguments"]["limit"] for c in srv.chamadas_tool] == [10, 10, 10]


async def test_paginar_vazio_faz_uma_chamada() -> None:
    srv = servidor_paginado(0)
    cliente, _ = montar(srv)

    assert await cliente.paginar("list_inventory", {}) == []
    assert len(srv.chamadas_tool) == 1


async def test_paginar_pagina_vazia_antes_do_total_nao_entra_em_loop() -> None:
    def handler(corpo: dict[str, Any], _req: httpx.Request) -> dict[str, Any]:
        page = corpo["params"]["arguments"]["page"]
        itens = [{"id": i} for i in range(300)] if page == 1 else []
        return {"total": 9999, "items": itens, "page": page, "limit": 300}

    srv = Servidor({"list_inventory": handler})
    cliente, _ = montar(srv)

    itens = await cliente.paginar("list_inventory", {})

    assert len(itens) == 300
    assert len(srv.chamadas_tool) == 2


# --- erros e retry ----------------------------------------------------------------------------


async def test_rate_limited_espera_retry_after_e_repete() -> None:
    respostas = [
        erro_tool("rate_limited", 429, retry_after_seconds=2),
        erro_tool("rate_limited", 429, retry_after_seconds=5),
        {"total": 1, "items": [{"id": 1}]},
    ]

    def handler(corpo: dict[str, Any], req: httpx.Request) -> Any:
        r = respostas.pop(0)
        return r(corpo, req) if callable(r) else r

    srv = Servidor({"list_brands": handler})
    cliente, relogio = montar(srv)

    resultado = await cliente.chamar("list_brands", {})

    assert resultado["total"] == 1
    assert relogio.dormidos == [2, 5]
    assert len(srv.chamadas_tool) == 3


async def test_rate_limited_esgota_tentativas_e_levanta_retentavel() -> None:
    srv = Servidor({"list_brands": erro_tool("rate_limited", 429, retry_after_seconds=1)})
    cliente, relogio = montar(srv, max_repeticoes_rate_limit=2)

    with pytest.raises(MercadoPhoneLimiteExcedido) as exc:
        await cliente.chamar("list_brands", {})

    assert exc.value.retentavel is True
    assert isinstance(exc.value, EstoqueIndisponivel)
    assert len(srv.chamadas_tool) == 3  # 1 + 2 repeticoes
    assert relogio.dormidos == [1, 1]


async def test_rate_limited_sem_retry_after_usa_espera_padrao() -> None:
    srv = Servidor({"list_brands": erro_tool("rate_limited", 429)})
    cliente, relogio = montar(srv, max_repeticoes_rate_limit=1)

    with pytest.raises(MercadoPhoneLimiteExcedido):
        await cliente.chamar("list_brands", {})

    assert len(relogio.dormidos) == 1
    assert 0 < relogio.dormidos[0] <= 60


async def test_rate_limited_com_espera_absurda_e_limitada() -> None:
    srv = Servidor({"list_brands": erro_tool("rate_limited", 429, retry_after_seconds=100000)})
    cliente, relogio = montar(srv, max_repeticoes_rate_limit=1)

    with pytest.raises(MercadoPhoneLimiteExcedido):
        await cliente.chamar("list_brands", {})

    assert relogio.dormidos[0] <= 60


@pytest.mark.parametrize("codigo", ["invalid_key", "store_missing_api_token"])
async def test_credencial_invalida_nao_repete_e_nao_e_retentavel(codigo: str) -> None:
    srv = Servidor({"list_brands": erro_tool(codigo, 401)})
    cliente, relogio = montar(srv)

    with pytest.raises(MercadoPhoneCredencialInvalida) as exc:
        await cliente.chamar("list_brands", {})

    assert exc.value.retentavel is False
    assert exc.value.codigo == codigo
    assert isinstance(exc.value, EstoqueIndisponivel)
    assert len(srv.chamadas_tool) == 1
    assert relogio.dormidos == []


@pytest.mark.parametrize("codigo", ["validation_error", "store_selection_required"])
async def test_erro_de_programacao_nao_e_retentavel(codigo: str) -> None:
    srv = Servidor({"list_brands": erro_tool(codigo, 422, "limit invalido")})
    cliente, _ = montar(srv)

    with pytest.raises(MercadoPhoneUsoIndevido) as exc:
        await cliente.chamar("list_brands", {})

    assert exc.value.retentavel is False
    assert exc.value.codigo == codigo
    assert exc.value.status == 422
    assert exc.value.hint == "dica"
    assert "limit invalido" in str(exc.value)
    assert len(srv.chamadas_tool) == 1


async def test_service_unavailable_e_retentavel() -> None:
    srv = Servidor({"list_brands": erro_tool("service_unavailable", 503)})
    cliente, _ = montar(srv)

    with pytest.raises(MercadoPhoneIndisponivel) as exc:
        await cliente.chamar("list_brands", {})

    assert exc.value.retentavel is True
    assert isinstance(exc.value, EstoqueIndisponivel)


async def test_http_5xx_e_retentavel() -> None:
    srv = Servidor({"list_brands": httpx.Response(502, text="bad gateway")})
    cliente, _ = montar(srv)

    with pytest.raises(MercadoPhoneIndisponivel) as exc:
        await cliente.chamar("list_brands", {})

    assert exc.value.retentavel is True


async def test_http_401_e_credencial_invalida() -> None:
    srv = Servidor({"list_brands": httpx.Response(401, text="nope")})
    cliente, _ = montar(srv)

    with pytest.raises(MercadoPhoneCredencialInvalida):
        await cliente.chamar("list_brands", {})


async def test_timeout_e_retentavel() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("lento", request=request)

    cliente, _ = montar(handler)

    with pytest.raises(MercadoPhoneIndisponivel) as exc:
        await cliente.chamar("list_brands", {})

    assert exc.value.retentavel is True


async def test_erro_jsonrpc_vira_excecao_tipada() -> None:
    def handler(c: dict[str, Any], _r: httpx.Request) -> httpx.Response:
        corpo = {
            "jsonrpc": "2.0",
            "id": c["id"],
            "error": {"code": -32602, "message": "params ruins"},
        }
        return sse(corpo)

    cliente, _ = montar(Servidor({"list_brands": handler}))

    with pytest.raises(MercadoPhoneUsoIndevido) as exc:
        await cliente.chamar("list_brands", {})

    assert "params ruins" in str(exc.value)


async def test_erro_jsonrpc_interno_e_retentavel() -> None:
    def handler(c: dict[str, Any], _r: httpx.Request) -> httpx.Response:
        corpo = {"jsonrpc": "2.0", "id": c["id"], "error": {"code": -32603, "message": "interno"}}
        return sse(corpo)

    cliente, _ = montar(Servidor({"list_brands": handler}))

    with pytest.raises(MercadoPhoneIndisponivel):
        await cliente.chamar("list_brands", {})


async def test_erro_desconhecido_5xx_e_retentavel_e_4xx_nao() -> None:
    cliente5, _ = montar(Servidor({"list_brands": erro_tool("coisa_nova", 500)}))
    cliente4, _ = montar(Servidor({"list_brands": erro_tool("coisa_nova", 400)}))

    with pytest.raises(ErroMercadoPhone) as e5:
        await cliente5.chamar("list_brands", {})
    with pytest.raises(ErroMercadoPhone) as e4:
        await cliente4.chamar("list_brands", {})

    assert e5.value.retentavel is True
    assert e4.value.retentavel is False


# --- allowlist --------------------------------------------------------------------------------


def test_allowlist_tem_so_o_que_o_projeto_usa() -> None:
    assert (
        frozenset(
            {
                "list_my_stores",
                "list_inventory",
                "list_brands",
                "list_salespeople",
                "list_payment_methods",
                "list_customers",
                "create_customer",
                "create_estimate",
            }
        )
        == FERRAMENTAS_PERMITIDAS
    )
    assert not any(nome.startswith("delete_") for nome in FERRAMENTAS_PERMITIDAS)


@pytest.mark.parametrize(
    "nome", ["delete_customer", "delete_estimate", "update_inventory", "", "list_brands "]
)
async def test_ferramenta_fora_da_allowlist_e_recusada_sem_rede(nome: str) -> None:
    srv = Servidor()
    cliente, _ = montar(srv)

    with pytest.raises(FerramentaNaoPermitida) as exc:
        await cliente.chamar(nome, {})
    assert exc.value.retentavel is False
    assert isinstance(exc.value, MercadoPhoneUsoIndevido)

    with pytest.raises(FerramentaNaoPermitida):
        await cliente.paginar(nome, {})

    assert srv.requisicoes == []  # nem initialize


# --- mascara da chave -------------------------------------------------------------------------


async def test_repr_mascara_a_chave() -> None:
    cliente, _ = montar(Servidor())

    assert CHAVE not in repr(cliente)
    assert CHAVE not in str(cliente)
    assert "***" in repr(cliente)


async def test_erros_nao_vazam_a_chave_mesmo_se_o_servidor_ecoa() -> None:
    srv = Servidor(
        {"list_brands": erro_tool("validation_error", 422, f"key {CHAVE} nao permitida")}
    )
    cliente, _ = montar(srv)

    with pytest.raises(MercadoPhoneUsoIndevido) as exc:
        await cliente.chamar("list_brands", {})

    assert CHAVE not in str(exc.value)
    assert CHAVE not in repr(exc.value)
    assert CHAVE not in (exc.value.hint or "")


async def test_erro_de_rede_com_url_na_mensagem_nao_vaza_a_chave() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"falha ao conectar em {request.url}", request=request)

    cliente, _ = montar(handler)

    with pytest.raises(MercadoPhoneIndisponivel) as exc:
        await cliente.chamar("list_brands", {})

    assert CHAVE not in str(exc.value)
    assert CHAVE not in repr(exc.value)
    assert exc.value.__cause__ is None
    assert exc.value.__suppress_context__ is True


async def test_logs_do_httpx_nao_vazam_a_chave(caplog: pytest.LogCaptureFixture) -> None:
    srv = Servidor({"list_brands": {"total": 0, "items": [], "page": 1, "limit": 300}})
    cliente, _ = montar(srv)

    with caplog.at_level(logging.DEBUG):
        await cliente.chamar("list_brands", {})

    assert any(r.name == "httpx" for r in caplog.records)  # o log existe...
    assert CHAVE not in caplog.text  # ...mas sem a chave
    assert CHAVE not in "".join(r.getMessage() for r in caplog.records)
