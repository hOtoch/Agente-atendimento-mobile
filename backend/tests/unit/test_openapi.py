"""OpenAPI do painel: rotas, schemas dos eventos SSE e sincronia com o cliente TypeScript."""

import json
from pathlib import Path

from app.adapters.inbound.http.openapi import gerar_openapi
from app.main import app

OPENAPI_FRONT = (
    Path(__file__).resolve().parents[3] / "frontend" / "src" / "lib" / "api" / "openapi.json"
)


def test_rotas_do_painel_estao_no_openapi() -> None:
    caminhos = gerar_openapi(app)["paths"]
    base = "/lojas/{loja_id}"
    assert "get" in caminhos[f"{base}/leads"]
    assert "get" in caminhos[f"{base}/leads/{{lead_id}}"]
    for acao in ("etapa", "assumir", "devolver", "mensagens"):
        assert "post" in caminhos[f"{base}/leads/{{lead_id}}/{acao}"]
    assert "get" in caminhos[f"{base}/eventos"]


def test_uniao_de_eventos_do_sse_esta_nos_componentes() -> None:
    schemas = gerar_openapi(app)["components"]["schemas"]
    evento = schemas["EventoPainel"]
    assert evento["discriminator"]["propertyName"] == "evento"
    assert {x["$ref"].rsplit("/", 1)[1] for x in evento["oneOf"]} == {
        "EventoEtapaMudouSchema",
        "EventoMensagemNovaSchema",
        "EventoDonoMudouSchema",
    }
    assert schemas["EventoEtapaMudouSchema"]["properties"]["evento"]["const"] == "EtapaMudou"


def test_openapi_do_frontend_esta_em_dia() -> None:
    """Se falhar: `npm run exportar:openapi && npm run gerar:api` em frontend/."""
    esperado = json.dumps(gerar_openapi(app), indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    assert OPENAPI_FRONT.read_text(encoding="utf-8") == esperado


def test_rotas_de_loja_declaram_o_cookie_de_sessao() -> None:
    esquema = gerar_openapi(app)
    assert esquema["components"]["securitySchemes"]["sessao"] == {
        "type": "apiKey",
        "in": "cookie",
        "name": "sessao",
    }
    paths = esquema["paths"]
    assert paths["/lojas/{loja_id}/leads"]["get"]["security"] == [{"sessao": []}]
    assert "security" not in paths["/webchat/{loja_id}/sessoes"]["post"]
    assert "security" not in paths["/health"]["get"]
