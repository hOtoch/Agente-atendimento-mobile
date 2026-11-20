"""CORS do painel: o front (outra origem) precisa chamar a API e abrir o SSE."""

import httpx

from app.infra.settings import Settings
from app.main import app


async def _preflight(origem: str) -> httpx.Response:
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        return await c.options(
            "/health",
            headers={"Origin": origem, "Access-Control-Request-Method": "POST"},
        )


async def test_origem_do_painel_e_liberada_por_padrao() -> None:
    r = await _preflight("http://localhost:3000")
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == "http://localhost:3000"


async def test_outra_origem_nao_e_liberada() -> None:
    r = await _preflight("http://evil.example")
    assert "access-control-allow-origin" not in r.headers


def test_cors_origins_vem_do_ambiente(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("CORS_ORIGINS", "https://a.com, https://b.com")
    assert Settings(_env_file=None).origens_cors == ["https://a.com", "https://b.com"]
