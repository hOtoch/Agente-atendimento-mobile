"""API da configuracao do follow-up, com o app real e um banco de teste isolado."""

from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.infra.dependencias import get_session
from app.main import app
from tests.integration.conftest import aplicar_migrations

pytestmark = pytest.mark.integration

CORPO: dict[str, Any] = {
    "ligado": True,
    "horas_por_etapa": {"interesse_qualificado": 2, "interesse_identificado": 24},
    "max_tentativas": 3,
    "intervalo_horas": 12,
    "hora_inicio": "08:30",
    "hora_fim": "19:00",
    "max_dias_parado": 5,
}


@pytest.fixture
async def client(db_url: str) -> AsyncIterator[httpx.AsyncClient]:
    await aplicar_migrations(db_url)
    engine = create_async_engine(db_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def _sessao() -> AsyncIterator[AsyncSession]:
        async with factory() as s:
            try:
                yield s
            except BaseException:
                await s.rollback()
                raise

    app.dependency_overrides[get_session] = _sessao
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        yield c
    app.dependency_overrides.clear()
    await engine.dispose()


async def _loja(client: httpx.AsyncClient) -> str:
    r = await client.post("/lojas", json={"nome": "Loja"})
    return str(r.json()["id"])


async def test_loja_sem_configuracao_vem_desligada_com_padroes(client: httpx.AsyncClient) -> None:
    loja = await _loja(client)
    r = await client.get(f"/lojas/{loja}/config/followup")
    assert r.status_code == 200
    corpo = r.json()
    assert corpo["ligado"] is False
    assert corpo["horas_por_etapa"]["interesse_qualificado"] == 2
    assert (corpo["hora_inicio"], corpo["hora_fim"]) == ("09:00", "18:00")


async def test_salva_e_le_de_volta(client: httpx.AsyncClient) -> None:
    loja = await _loja(client)
    r = await client.put(f"/lojas/{loja}/config/followup", json=CORPO)
    assert r.status_code == 200, r.text
    assert r.json() == CORPO
    assert (await client.get(f"/lojas/{loja}/config/followup")).json() == CORPO
    # regravar atualiza (upsert)
    r2 = await client.put(
        f"/lojas/{loja}/config/followup", json={**CORPO, "ligado": False, "max_tentativas": 1}
    )
    assert r2.status_code == 200
    atual = (await client.get(f"/lojas/{loja}/config/followup")).json()
    assert (atual["ligado"], atual["max_tentativas"]) == (False, 1)


async def test_recusa_configuracao_invalida_com_erro_por_campo(client: httpx.AsyncClient) -> None:
    loja = await _loja(client)
    r = await client.put(f"/lojas/{loja}/config/followup", json={**CORPO, "max_tentativas": 0})
    assert r.status_code == 422
    assert r.json()["erros"][0]["caminho"] == "max_tentativas"
    r = await client.put(
        f"/lojas/{loja}/config/followup", json={**CORPO, "horas_por_etapa": {"venda_fechada": 1}}
    )
    assert r.status_code == 422
    assert r.json()["erros"][0]["caminho"] == "horas_por_etapa.venda_fechada"


async def test_loja_inexistente_da_404(client: httpx.AsyncClient) -> None:
    r = await client.get(f"/lojas/{uuid4()}/config/followup")
    assert r.status_code == 404
