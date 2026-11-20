"""ERP simulado falso (respx) para testes do `ErpSimuladoAdapter`."""

from __future__ import annotations

import json
import math
from collections.abc import Sequence
from typing import Any

import httpx
import respx

BASE_URL = "http://erp.test"
TOKEN = "token-teste"


def produto(sku: str, descricao: str, preco: str = "1000.00", estoque: int = 1) -> dict[str, Any]:
    return {
        "sku": sku,
        "descricao": descricao,
        "preco": preco,
        "estoque": estoque,
        "atualizado_em": "2026-11-01T10:00:00-03:00",
    }


def montar_erp(router: respx.MockRouter, produtos: Sequence[dict[str, Any]]) -> None:
    """Registra `GET /produtos` (paginado, exige Bearer) e `GET /produtos/{sku}`."""

    def _auth(request: httpx.Request) -> httpx.Response | None:
        if request.headers.get("authorization") != f"Bearer {TOKEN}":
            return httpx.Response(401, json={"detail": "token ausente ou invalido"})
        return None

    def _listar(request: httpx.Request) -> httpx.Response:
        if (negado := _auth(request)) is not None:
            return negado
        pagina = int(request.url.params.get("pagina", "1"))
        tamanho = int(request.url.params.get("tamanho", "50"))
        total = len(produtos)
        inicio = (pagina - 1) * tamanho
        corpo = {
            "itens": list(produtos[inicio : inicio + tamanho]),
            "pagina": pagina,
            "tamanho": tamanho,
            "total": total,
            "total_paginas": max(1, math.ceil(total / tamanho)),
        }
        return httpx.Response(200, content=json.dumps(corpo))

    def _obter(request: httpx.Request) -> httpx.Response:
        if (negado := _auth(request)) is not None:
            return negado
        sku = request.url.path.rsplit("/", 1)[-1]
        for p in produtos:
            if p["sku"] == sku:
                return httpx.Response(200, content=json.dumps(p))
        return httpx.Response(404, json={"detail": "produto nao encontrado"})

    router.get(f"{BASE_URL}/produtos").mock(side_effect=_listar)
    router.get(url__regex=rf"{BASE_URL}/produtos/.+").mock(side_effect=_obter)
