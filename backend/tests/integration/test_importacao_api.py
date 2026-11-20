"""API de importacao (multipart) com o app real e banco de teste isolado."""

from collections.abc import AsyncIterator
from io import BytesIO

import httpx
import pytest
from openpyxl import load_workbook
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.infra.dependencias import get_session
from app.main import app
from tests.integration.conftest import aplicar_migrations
from tests.unit.importacao.planilhas import estoque_xlsx, troca_xlsx

pytestmark = pytest.mark.integration

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


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
    r = await client.post("/lojas", json={"nome": "Loja API"})
    return str(r.json()["id"])


def _arq(conteudo: bytes) -> dict[str, tuple[str, bytes, str]]:
    return {"arquivo": ("planilha.xlsx", conteudo, XLSX)}


async def test_importar_estoque_aplicar_e_listar(client: httpx.AsyncClient) -> None:
    loja = await _loja(client)
    conteudo = estoque_xlsx([["A1", "iPhone 15", 128, "Preto", "novo", "4.000,50", 2, None]])
    r = await client.post(f"/lojas/{loja}/importar/estoque?modo=aplicar", files=_arq(conteudo))
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["ok"] is True and corpo["erros"] == [] and corpo["resumo"]["linhas"] == 1
    est = (await client.get(f"/lojas/{loja}/config/estoque")).json()
    assert [x["sku"] for x in est["estoque"]] == ["A1"]


async def test_modo_padrao_e_validar_e_nao_grava(client: httpx.AsyncClient) -> None:
    loja = await _loja(client)
    conteudo = estoque_xlsx([["A1", "iPhone 15", 128, "Preto", "novo", 4000, 2, None]])
    r = await client.post(f"/lojas/{loja}/importar/estoque", files=_arq(conteudo))
    assert r.status_code == 200 and r.json()["ok"] is True
    est = (await client.get(f"/lojas/{loja}/config/estoque")).json()
    assert "A1" not in str(est)


async def test_planilha_com_erro_retorna_422_com_relatorio(client: httpx.AsyncClient) -> None:
    loja = await _loja(client)
    conteudo = troca_xlsx(
        [
            ["iPhone 16", 128, 3100, 0, 0, 0, 0, 80],
            ["iPhone 15", "abc", 3100, 0, 0, 0, 0, 80],
        ]
    )
    r = await client.post(f"/lojas/{loja}/importar/troca?modo=aplicar", files=_arq(conteudo))
    assert r.status_code == 422
    corpo = r.json()
    assert corpo["ok"] is False
    assert corpo["erros"][0]["caminho"] == "troca!B3"
    troca = (await client.get(f"/lojas/{loja}/config/troca")).json()
    assert "iphone 16" not in str(troca).lower()  # nada gravado


async def test_arquivo_invalido_e_loja_inexistente(client: httpx.AsyncClient) -> None:
    loja = await _loja(client)
    r = await client.post(f"/lojas/{loja}/importar/troca", files=_arq(b"lixo"))
    assert r.status_code == 422 and r.json()["erros"][0]["caminho"] == "arquivo"
    r = await client.post(
        "/lojas/00000000-0000-0000-0000-000000000000/importar/troca", files=_arq(b"lixo")
    )
    assert r.status_code == 404
    r = await client.post(f"/lojas/{loja}/importar/xyz", files=_arq(b"lixo"))
    assert r.status_code == 422


async def test_baixar_modelos(client: httpx.AsyncClient) -> None:
    for tipo, aba in (("troca", "Tabela de troca"), ("taxas", "Taxas"), ("estoque", "Estoque")):
        r = await client.get(f"/modelos/{tipo}")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith(XLSX)
        assert f"modelo-{tipo}.xlsx" in r.headers["content-disposition"]
        assert aba in load_workbook(BytesIO(r.content)).sheetnames
    assert (await client.get("/modelos/xyz")).status_code == 422
