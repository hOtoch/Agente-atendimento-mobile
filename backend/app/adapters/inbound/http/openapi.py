"""OpenAPI do app + os schemas dos eventos SSE (que nenhuma rota devolve como JSON).

`scripts/exportar_openapi.py` grava o resultado para o cliente TypeScript.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi
from pydantic import TypeAdapter

from app.adapters.inbound.http.schemas_painel import EventoPainelSchema

_REF = "#/components/schemas/{model}"


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
    app.openapi_schema = esquema
    return esquema


def registrar_openapi(app: FastAPI) -> None:
    app.openapi = lambda: gerar_openapi(app)  # type: ignore[method-assign]
