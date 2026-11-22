"""Servidor MCP do Mercado Phone falso, em memoria (httpx.MockTransport), com dados SINTETICOS.

Atende `initialize`, `notifications/initialized` e `tools/call` de `list_my_stores`, `list_brands`
e `list_inventory` (paginado como o real: `page`, `limit` <= 300, `total`). Registra cada chamada
de ferramenta em `chamadas` e permite injetar falha numa pagina do inventario.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

import httpx

URL = "https://mp.exemplo.test/mcp/platform/"
CHAVE = "chave-de-teste-123"
MARCAS_PADRAO: list[dict[str, Any]] = [
    {"id": 501, "name": "Apple"},
    {"id": 502, "name": "Samsung"},
]


def item(
    erp_id: int,
    *,
    sku: str | None = None,
    modelo: str = "IPHONE 15 PRO",
    obs: str = "Loja A",
    quantidade: float = 1.0,
    estado: str = "SEMINOVO",
    capacidade: str = "256gb",
    preco: float = 4200,
    marca_id: int = 501,
    tipo: str = "Celular",
    disponibilidade: str = "Disponível para venda",
) -> dict[str, Any]:
    """Item sintetico no formato cru de `list_inventory`."""
    return {
        "id": erp_id,
        "sku": sku if sku is not None else f"TESTE-{erp_id:05d}",
        "aparelhoDescricao": modelo,
        "quantidade": quantidade,
        "disponibilidade": disponibilidade,
        "marcaId": marca_id,
        "tipoProdutoDescricao": tipo,
        "gbDescricao": capacidade,
        "corDescricao": "PRETO",
        "estadoProdutoDescricao": estado,
        "saudeBateria": None,
        "valorVenda": preco,
        "obs": obs,
        "snAcessorio": 0,
        "snPeca": 0,
        "snServico": 0,
    }


def resposta_sse(corpo: dict[str, Any]) -> httpx.Response:
    return httpx.Response(
        200,
        headers={"content-type": "text/event-stream"},
        text=f"event: message\ndata: {json.dumps(corpo)}\n\n",
    )


class McpFalso:
    """`unidades`: `{system_unit_id: [itens crus]}`. Cada instancia e um `MockTransport` handler."""

    def __init__(
        self,
        unidades: Mapping[int, Sequence[dict[str, Any]]],
        *,
        marcas: Sequence[dict[str, Any]] = MARCAS_PADRAO,
        falha_na_pagina: Mapping[int, httpx.Response] | None = None,
        lojas_da_chave: Sequence[int] | None = None,
        marcas_exigem_loja: bool = False,
    ) -> None:
        self.unidades = {k: list(v) for k, v in unidades.items()}
        self.marcas = list(marcas)
        self.falha_na_pagina = dict(falha_na_pagina or {})
        self.lojas_da_chave = list(lojas_da_chave) if lojas_da_chave is not None else list(unidades)
        self.marcas_exigem_loja = marcas_exigem_loja
        self.chamadas: list[tuple[str, dict[str, Any]]] = []

    def cliente_http(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self))

    def paginas_lidas(self, unidade: int) -> list[int]:
        return [
            a["page"]
            for nome, a in self.chamadas
            if nome == "list_inventory" and a.get("system_unit_id") == unidade
        ]

    def leituras_do_inventario(self) -> int:
        """Quantas leituras completas comecaram (chamadas a `list_inventory` pagina 1)."""
        return sum(1 for n, a in self.chamadas if n == "list_inventory" and a.get("page") == 1)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        corpo = json.loads(request.content)
        metodo = corpo["method"]
        if metodo == "notifications/initialized":
            return httpx.Response(202)
        if metodo == "initialize":
            return resposta_sse(
                {
                    "jsonrpc": "2.0",
                    "id": corpo["id"],
                    "result": {"protocolVersion": "2025-06-18", "capabilities": {}},
                }
            )
        nome = corpo["params"]["name"]
        args = corpo["params"]["arguments"]
        self.chamadas.append((nome, args))
        if nome == "list_inventory":
            falha = self.falha_na_pagina.get(args.get("page", 1))
            if falha is not None:
                return falha
        payload = self._payload(nome, args)
        resultado: dict[str, Any] = {"content": [{"type": "text", "text": json.dumps(payload)}]}
        if isinstance(payload, dict) and "code" in payload and "error" in payload:
            resultado["isError"] = True
        return resposta_sse({"jsonrpc": "2.0", "id": corpo["id"], "result": resultado})

    def _payload(self, nome: str, args: dict[str, Any]) -> Any:
        if nome == "list_my_stores":
            # Formato real: {"cross_unit", "stores": [{"system_unit_id", "name"}], "note"}.
            lojas = [{"system_unit_id": u, "name": f"Unidade {u}"} for u in self.lojas_da_chave]
            return {"cross_unit": len(lojas) > 1, "stores": lojas, "note": None}
        if nome == "list_brands":
            if self.marcas_exigem_loja and "system_unit_id" not in args:
                return {
                    "error": "informe system_unit_id",
                    "status": 422,
                    "code": "store_selection_required",
                }
            return self._pagina(self.marcas, args)
        if nome == "list_inventory":
            return self._pagina(self.unidades.get(args.get("system_unit_id"), []), args)
        raise AssertionError(f"ferramenta inesperada: {nome}")

    @staticmethod
    def _pagina(todos: list[dict[str, Any]], args: dict[str, Any]) -> dict[str, Any]:
        pagina, limite = args.get("page", 1), args.get("limit", 300)
        inicio = (pagina - 1) * limite
        return {
            "total": len(todos),
            "page": pagina,
            "limit": limite,
            "items": todos[inicio : inicio + limite],
        }
