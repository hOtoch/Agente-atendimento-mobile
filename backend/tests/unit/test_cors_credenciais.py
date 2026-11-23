"""CORS com cookie de sessao: credenciais liberadas so para as origens explicitas."""

import httpx

from app.main import app


async def test_preflight_devolve_allow_credentials() -> None:
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        r = await c.options(
            "/health",
            headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "GET"},
        )
    assert r.headers["access-control-allow-credentials"] == "true"
    assert r.headers["access-control-allow-origin"] == "http://localhost:3000"
