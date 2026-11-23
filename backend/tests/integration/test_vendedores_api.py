"""API de vendedores (GET/PUT /lojas/{id}/config/vendedores) com o app real e banco isolado."""

from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.adapters.outbound.db.models import Lead, Vendedor
from app.infra.dependencias import get_session
from app.main import app
from tests.integration.conftest import aplicar_migrations
from tests.integration.lojas import criar_loja_no_banco

pytestmark = pytest.mark.integration


@pytest.fixture
async def ctx(db_url: str) -> AsyncIterator[tuple[httpx.AsyncClient, async_sessionmaker[Any]]]:
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
        yield c, factory
    app.dependency_overrides.clear()
    await engine.dispose()


async def criar_loja(client: httpx.AsyncClient) -> str:
    return await criar_loja_no_banco("Loja V")


def corpo(*itens: dict[str, Any]) -> dict[str, Any]:
    return {"vendedores": list(itens)}


async def test_get_vazio(ctx: Any) -> None:
    client, _ = ctx
    loja = await criar_loja(client)
    r = await client.get(f"/lojas/{loja}/config/vendedores")
    assert r.status_code == 200
    assert r.json() == {"vendedores": []}


async def test_put_cria_e_get_devolve(ctx: Any) -> None:
    client, _ = ctx
    loja = await criar_loja(client)
    r = await client.put(
        f"/lojas/{loja}/config/vendedores",
        json=corpo(
            {"nome": "Ana", "telefone": "+55 11 90000-0001", "peso_percentual": "60"},
            {"nome": "Bruno", "peso_percentual": 40},
        ),
    )
    assert r.status_code == 200, r.text
    dados = r.json()["vendedores"]
    assert [v["nome"] for v in dados] == ["Ana", "Bruno"]
    assert dados[0]["telefone"] == "+55 11 90000-0001"
    assert dados[1]["telefone"] is None
    assert all(v["ativo"] is True and UUID(v["id"]) for v in dados)
    assert float(dados[0]["peso_percentual"]) == 60
    assert (await client.get(f"/lojas/{loja}/config/vendedores")).json() == r.json()


async def test_put_mantem_id_cria_novo_e_desativa_o_que_sumiu(ctx: Any) -> None:
    client, factory = ctx
    loja = await criar_loja(client)
    r = await client.put(
        f"/lojas/{loja}/config/vendedores",
        json=corpo(
            {"nome": "Ana", "peso_percentual": "50"}, {"nome": "Bruno", "peso_percentual": "50"}
        ),
    )
    ana, bruno = r.json()["vendedores"]
    r = await client.put(
        f"/lojas/{loja}/config/vendedores",
        json=corpo(
            {"id": ana["id"], "nome": "Ana Souza", "peso_percentual": "70"},
            {"nome": "Carla", "peso_percentual": "30"},
        ),
    )
    assert r.status_code == 200, r.text
    por_id = {v["id"]: v for v in r.json()["vendedores"]}
    assert por_id[ana["id"]]["nome"] == "Ana Souza"
    assert por_id[bruno["id"]]["ativo"] is False
    assert len(por_id) == 3
    async with factory() as s:
        assert len((await s.execute(select(Vendedor))).scalars().all()) == 3


async def test_put_nao_apaga_vendedor_com_lead(ctx: Any) -> None:
    client, factory = ctx
    loja = await criar_loja(client)
    r = await client.put(
        f"/lojas/{loja}/config/vendedores",
        json=corpo(
            {"nome": "Ana", "peso_percentual": "50"}, {"nome": "Bruno", "peso_percentual": "50"}
        ),
    )
    ana, bruno = r.json()["vendedores"]
    async with factory() as s:
        s.add(
            Lead(
                loja_id=UUID(loja),
                telefone="s1",
                canal="webchat",
                dono="vendedor",
                vendedor_id=UUID(bruno["id"]),
            )
        )
        await s.commit()
    r = await client.put(
        f"/lojas/{loja}/config/vendedores",
        json=corpo({"id": ana["id"], "nome": "Ana", "peso_percentual": "100"}),
    )
    assert r.status_code == 200
    async with factory() as s:
        lead = (await s.execute(select(Lead))).scalar_one()
        assert lead.vendedor_id == UUID(bruno["id"])


async def test_put_soma_diferente_de_100_da_422_uniforme(ctx: Any) -> None:
    client, _ = ctx
    loja = await criar_loja(client)
    r = await client.put(
        f"/lojas/{loja}/config/vendedores",
        json=corpo(
            {"nome": "Ana", "peso_percentual": "60"}, {"nome": "Bruno", "peso_percentual": "30"}
        ),
    )
    assert r.status_code == 422
    assert [e["caminho"] for e in r.json()["erros"]] == ["vendedores"]
    assert (await client.get(f"/lojas/{loja}/config/vendedores")).json() == {"vendedores": []}


async def test_put_erros_por_linha(ctx: Any) -> None:
    client, _ = ctx
    loja = await criar_loja(client)
    r = await client.put(
        f"/lojas/{loja}/config/vendedores",
        json=corpo(
            {"nome": "Ana", "peso_percentual": "100"},
            {"nome": "", "peso_percentual": "10"},
            {"nome": "Carla", "peso_percentual": "130"},
        ),
    )
    assert r.status_code == 422
    assert [e["caminho"] for e in r.json()["erros"]] == [
        "vendedores[1].nome",
        "vendedores[2].peso_percentual",
    ]


async def test_put_id_de_outra_loja_da_422(ctx: Any) -> None:
    client, _ = ctx
    a = await criar_loja(client)
    b = await criar_loja(client)
    r = await client.put(
        f"/lojas/{a}/config/vendedores", json=corpo({"nome": "Ana", "peso_percentual": "100"})
    )
    ana = r.json()["vendedores"][0]
    r = await client.put(
        f"/lojas/{b}/config/vendedores",
        json=corpo({"id": ana["id"], "nome": "Ana", "peso_percentual": "100"}),
    )
    assert r.status_code == 422
    assert r.json()["erros"][0]["caminho"] == "vendedores[0].id"


async def test_campo_obrigatorio_ausente_da_422_com_caminho(ctx: Any) -> None:
    client, _ = ctx
    loja = await criar_loja(client)
    r = await client.put(f"/lojas/{loja}/config/vendedores", json=corpo({"nome": "Ana"}))
    assert r.status_code == 422
    assert r.json()["erros"][0]["caminho"] == "vendedores[0].peso_percentual"


async def test_loja_inexistente_404(ctx: Any) -> None:
    client, _ = ctx
    r = await client.get("/lojas/00000000-0000-0000-0000-000000000001/config/vendedores")
    assert r.status_code == 404
    r = await client.put(
        "/lojas/00000000-0000-0000-0000-000000000001/config/vendedores",
        json=corpo({"nome": "Ana", "peso_percentual": "100"}),
    )
    assert r.status_code == 404


async def test_checklist_fica_completo_apos_salvar(ctx: Any) -> None:
    client, _ = ctx
    loja = await criar_loja(client)
    await client.put(
        f"/lojas/{loja}/config/vendedores",
        json=corpo(
            {"nome": "Ana", "peso_percentual": "60"}, {"nome": "Bruno", "peso_percentual": "40"}
        ),
    )
    itens = (await client.get(f"/lojas/{loja}/onboarding/checklist")).json()["itens"]
    assert next(i for i in itens if i["chave"] == "vendedores")["completo"] is True
