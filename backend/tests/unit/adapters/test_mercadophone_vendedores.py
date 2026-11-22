"""Leitor de vendedores do Mercado Phone (`list_salespeople`) sobre `httpx.MockTransport`.

Respostas sinteticas no formato real; nenhuma chamada ao servico real.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from app.adapters.outbound.mercadophone.cliente import ClienteMercadoPhone
from app.adapters.outbound.mercadophone.vendedores import (
    LeitorVendedoresMercadoPhone,
    nome_legivel,
)
from app.application.config.vendedores_erp import VendedorErp
from app.application.relogio import RelogioFalso

URL = "https://mp.exemplo.test/mcp/platform/"


class ServidorSalespeople:
    def __init__(self, paginas: list[dict[str, Any]]) -> None:
        self.paginas = paginas
        self.argumentos: list[dict[str, Any]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        corpo = json.loads(request.content)
        metodo = corpo["method"]
        if metodo == "notifications/initialized":
            return httpx.Response(202)
        if metodo == "initialize":
            resultado: dict[str, Any] = {"protocolVersion": "2025-06-18", "capabilities": {}}
        else:
            assert corpo["params"]["name"] == "list_salespeople"
            args = corpo["params"]["arguments"]
            self.argumentos.append(args)
            payload = self.paginas[args["page"] - 1]
            resultado = {"content": [{"type": "text", "text": json.dumps(payload)}]}
        msg = {"jsonrpc": "2.0", "id": corpo["id"], "result": resultado}
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text=f"event: message\ndata: {json.dumps(msg)}\n\n",
        )


def leitor(servidor: ServidorSalespeople) -> LeitorVendedoresMercadoPhone:
    http = httpx.AsyncClient(transport=httpx.MockTransport(servidor))
    cliente = ClienteMercadoPhone(http, URL, "chave-x", relogio=RelogioFalso())
    return LeitorVendedoresMercadoPhone(cliente)


def item(id_: Any, nome: str, ativo: Any = 1, **extra: Any) -> dict[str, Any]:
    return {
        "id": id_,
        "name": nome,
        "cpf": None,
        "codigoIntegracao": None,
        "snAtivo": ativo,
        **extra,
    }


async def test_mapeia_id_nome_e_ativo() -> None:
    srv = ServidorSalespeople(
        [
            {
                "total": 3,
                "items": [item(9, "FULANO DE SOUZA"), item(10, "Beltrana", 0), item(11, "X", None)],
                "page": 1,
                "limit": 100,
            }
        ]
    )
    vendedores = await leitor(srv).listar(12)

    assert vendedores == [
        VendedorErp("9", "Fulano de Souza", True),
        VendedorErp("10", "Beltrana", False),
        VendedorErp("11", "X", False),
    ]


async def test_pede_a_unidade_da_loja_e_junta_as_paginas() -> None:
    primeira = [item(i, f"VENDEDOR {i}") for i in range(1, 301)]
    segunda = [item(301, "ULTIMO")]
    srv = ServidorSalespeople(
        [
            {"total": 301, "items": primeira, "page": 1, "limit": 300},
            {"total": 301, "items": segunda, "page": 2, "limit": 300},
        ]
    )
    vendedores = await leitor(srv).listar(12)

    assert len(vendedores) == 301
    assert [a["page"] for a in srv.argumentos] == [1, 2]
    assert all(a["system_unit_id"] == 12 for a in srv.argumentos)


async def test_descarta_itens_sem_id_ou_sem_nome() -> None:
    srv = ServidorSalespeople(
        [
            {
                "total": 4,
                "items": [item(None, "SEM ID"), item(5, "   "), item(6, "Ok"), "lixo"],
                "page": 1,
                "limit": 100,
            }
        ]
    )
    assert await leitor(srv).listar(1) == [VendedorErp("6", "Ok", True)]


async def test_so_snativo_igual_a_1_conta_como_ativo() -> None:
    srv = ServidorSalespeople(
        [
            {
                "total": 4,
                "items": [item(1, "A", 1), item(2, "B", 2), item(3, "C", "1"), item(4, "D", True)],
                "page": 1,
                "limit": 100,
            }
        ]
    )
    ativos = {v.codigo_erp: v.ativo for v in await leitor(srv).listar(1)}
    assert ativos == {"1": True, "2": False, "3": False, "4": True}


@pytest.mark.parametrize(
    ("bruto", "esperado"),
    [
        ("FULANO DE TAL", "Fulano de Tal"),
        ("  MARIA   DAS DORES ", "Maria das Dores"),
        ("JOSÉ ANTÔNIO D'ÁVILA", "José Antônio D'Ávila"),
        ("ANA-MARIA E SILVA", "Ana-Maria e Silva"),
        ("DE SOUZA", "De Souza"),
        ("Beltrana Silva", "Beltrana Silva"),
        ("joão da Silva", "joão da Silva"),
        ("", ""),
    ],
)
def test_nome_legivel(bruto: str, esperado: str) -> None:
    assert nome_legivel(bruto) == esperado
