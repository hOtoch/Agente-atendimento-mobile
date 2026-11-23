"""Dependencia `loja_autorizada`: a loja da URL tem de ser a loja da sessao."""

from collections.abc import AsyncIterator
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import APIRouter, Depends, FastAPI

from app.adapters.inbound.http.erros import registrar_handlers
from app.application.auth.memoria import MemoriaSessoes
from app.infra.dependencias import get_sessoes, loja_autorizada

pytestmark = pytest.mark.autenticacao_real

Ambiente = tuple[httpx.AsyncClient, MemoriaSessoes]


@pytest.fixture
async def ambiente() -> AsyncIterator[Ambiente]:
    sessoes = MemoriaSessoes()
    api = FastAPI()
    registrar_handlers(api)
    router = APIRouter(dependencies=[Depends(loja_autorizada)])

    @router.get("/lojas/{loja_id}/ping")
    async def ping(loja_id: UUID) -> dict[str, str]:
        return {"loja": str(loja_id)}

    api.include_router(router)
    api.dependency_overrides[get_sessoes] = lambda: sessoes
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api), base_url="http://t") as c:
        yield c, sessoes


async def test_sem_sessao_401(ambiente: Ambiente) -> None:
    c, _ = ambiente
    r = await c.get(f"/lojas/{uuid4()}/ping")
    assert r.status_code == 401
    assert r.json()["erros"][0]["caminho"] == "sessao"


async def test_token_desconhecido_401(ambiente: Ambiente) -> None:
    c, _ = ambiente
    r = await c.get(f"/lojas/{uuid4()}/ping", cookies={"sessao": "inventado"})
    assert r.status_code == 401


async def test_sessao_de_outra_loja_403(ambiente: Ambiente) -> None:
    c, sessoes = ambiente
    token = await sessoes.criar(uuid4(), uuid4())
    r = await c.get(f"/lojas/{uuid4()}/ping", cookies={"sessao": token})
    assert r.status_code == 403
    assert r.json()["erros"][0]["caminho"] == "loja_id"


async def test_sessao_da_loja_certa_passa(ambiente: Ambiente) -> None:
    c, sessoes = ambiente
    loja = uuid4()
    token = await sessoes.criar(uuid4(), loja)
    r = await c.get(f"/lojas/{loja}/ping", cookies={"sessao": token})
    assert r.status_code == 200
    assert r.json() == {"loja": str(loja)}
