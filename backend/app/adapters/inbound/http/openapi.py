"""OpenAPI do app + os schemas dos eventos SSE (que nenhuma rota devolve como JSON).

`scripts/exportar_openapi.py` grava o resultado para o cliente TypeScript.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi
from pydantic import TypeAdapter

from app.adapters.inbound.http.schemas_painel import EventoPainelSchema
from app.infra.dependencias import COOKIE_SESSAO

_REF = "#/components/schemas/{model}"


def _declarar_sessao(esquema: dict[str, Any]) -> None:
    """Cookie de sessao como security scheme; as rotas `/lojas/{loja_id}/...` o exigem."""
    esquema["components"].setdefault("securitySchemes", {})["sessao"] = {
        "type": "apiKey",
        "in": "cookie",
        "name": COOKIE_SESSAO,
    }
    for caminho, operacoes in esquema["paths"].items():
        if not caminho.startswith("/lojas/{loja_id}"):
            continue
        for operacao in operacoes.values():
            operacao["security"] = [{"sessao": []}]


def gerar_openapi(app: FastAPI) -> dict[str, Any]:
    if app.openapi_schema is not None:
        return app.openapi_schema
    esquema = get_openapi(
        title=app.title, version=app.version, routes=app.routes, description=app.description
    )
    evento = TypeAdapter(EventoPainelSchema).json_schema(ref_template=_REF)
    componentes = esquema.setdefault("components", {}).setdefault("schemas", {})
    componentes.update(evento.pop("$defs", {}))
    componentes["EventoPainel"] = evento
    _declarar_sessao(esquema)
    app.openapi_schema = esquema
    return esquema


def registrar_openapi(app: FastAPI) -> None:
    app.openapi = lambda: gerar_openapi(app)  # type: ignore[method-assign]
