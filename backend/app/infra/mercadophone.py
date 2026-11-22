"""Fabrica do cliente do Mercado Phone (MCP). Sem chave configurada, a integracao fica desligada."""

from __future__ import annotations

from functools import lru_cache

import httpx

from app.adapters.outbound.mercadophone.cliente import ClienteMercadoPhone
from app.infra.settings import get_settings


class MercadoPhoneNaoConfigurado(Exception):
    """`MERCADOPHONE_API_KEY` ausente no .env."""


@lru_cache
def get_cliente_mercadophone() -> ClienteMercadoPhone:
    settings = get_settings()
    if not settings.mercadophone_api_key:
        raise MercadoPhoneNaoConfigurado("MERCADOPHONE_API_KEY nao configurada")
    return ClienteMercadoPhone(
        httpx.AsyncClient(), settings.mercadophone_mcp_url, settings.mercadophone_api_key
    )
