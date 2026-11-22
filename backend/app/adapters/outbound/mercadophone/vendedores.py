"""Leitor de vendedores do Mercado Phone: `list_salespeople` -> `VendedorErp`.

Formato do ERP (valores ilustrativos): `{"total": 1, "items": [{"id": 9, "name": "FULANO",
"cpf": null, "codigoIntegracao": null, "snAtivo": 1}], "page": 1, "limit": 100}`.
`codigo_erp = str(id)`; so `snAtivo == 1` e ativo; nome em CAIXA ALTA vira titulo.
"""

from __future__ import annotations

import re
from typing import Any

from app.adapters.outbound.mercadophone.cliente import ClienteMercadoPhone
from app.application.config.vendedores_erp import VendedorErp

FERRAMENTA = "list_salespeople"
ARGUMENTO_UNIDADE = "system_unit_id"
_PARTICULAS = frozenset({"de", "da", "do", "das", "dos", "e"})
_PALAVRA = re.compile(r"[^\W\d_]+")


def nome_legivel(bruto: str) -> str:
    """Nome em CAIXA ALTA vira titulo (particulas em minusculas); senao so tira espacos extras."""
    limpo = " ".join(bruto.split())
    if not limpo or limpo != limpo.upper():
        return limpo
    posicao = 0

    def _palavra(m: re.Match[str]) -> str:
        nonlocal posicao
        palavra = m.group(0)
        primeira = posicao == 0
        posicao += 1
        if not primeira and palavra in _PARTICULAS:
            return palavra
        return palavra.capitalize()

    return _PALAVRA.sub(_palavra, limpo.lower())


class LeitorVendedoresMercadoPhone:
    """Implementa `LeitorVendedoresErp` sobre o cliente MCP (so leitura)."""

    def __init__(self, cliente: ClienteMercadoPhone) -> None:
        self._cliente = cliente

    async def listar(self, system_unit_id: int) -> list[VendedorErp]:
        itens = await self._cliente.paginar(FERRAMENTA, {ARGUMENTO_UNIDADE: system_unit_id})
        vendedores: list[VendedorErp] = []
        for item in itens:
            vendedor = _mapear(item)
            if vendedor is not None:
                vendedores.append(vendedor)
        return vendedores


def _mapear(item: Any) -> VendedorErp | None:
    if not isinstance(item, dict):
        return None
    id_ = item.get("id")
    nome = nome_legivel(str(item.get("name") or ""))
    if id_ is None or isinstance(id_, bool) or not nome:
        return None
    return VendedorErp(codigo_erp=str(id_), nome=nome, ativo=item.get("snAtivo") == 1)
