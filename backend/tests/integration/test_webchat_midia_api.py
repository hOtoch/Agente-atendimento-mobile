"""Upload e entrega de midia do webchat (app real + Postgres isolado; disco em tmp_path)."""

from collections.abc import AsyncIterator
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.adapters.outbound.midia.disco import ArmazenamentoMidiaDisco
from app.application.midia import ReceberMidia
from app.infra.dependencias import get_armazenamento_midia, get_receber_midia, get_session
from app.main import app
from tests.integration.conftest import aplicar_migrations
from tests.integration.lojas import criar_loja_no_banco

pytestmark = pytest.mark.integration

LIMITE = 1024
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32


@pytest.fixture
async def client(db_url: str, tmp_path: Path) -> AsyncIterator[httpx.AsyncClient]:
    await aplicar_migrations(db_url)
    engine = create_async_engine(db_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def _sessao() -> AsyncIterator[AsyncSession]:
        async with factory() as s:
            yield s

    armazenamento = ArmazenamentoMidiaDisco(tmp_path)
    receber = ReceberMidia(armazenamento, limite_bytes=LIMITE)
    app.dependency_overrides[get_armazenamento_midia] = lambda: armazenamento
    app.dependency_overrides[get_session] = _sessao
    app.dependency_overrides[get_receber_midia] = lambda: receber
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        yield c
    app.dependency_overrides.clear()
    await engine.dispose()


async def _loja(c: httpx.AsyncClient) -> str:
    return await criar_loja_no_banco("Loja Midia")


def _arquivo(conteudo: bytes, tipo: str) -> dict[str, tuple[str, bytes, str]]:
    return {"arquivo": ("arquivo", conteudo, tipo)}


async def test_upload_devolve_midia_url_e_a_midia_e_servida(client: httpx.AsyncClient) -> None:
    loja = await _loja(client)
    r = await client.post(f"/webchat/{loja}/midias", files=_arquivo(PNG, "image/png"))
    assert r.status_code == 201
    url = r.json()["midia_url"]
    assert url.startswith("http://t/midias/")
    servida = await client.get(url)
    assert servida.status_code == 200
    assert servida.headers["content-type"] == "image/png"
    assert servida.content == PNG


async def test_audio_com_codec_no_content_type(client: httpx.AsyncClient) -> None:
    loja = await _loja(client)
    r = await client.post(
        f"/webchat/{loja}/midias", files=_arquivo(b"audio", "audio/webm;codecs=opus")
    )
    assert r.status_code == 201
    assert (await client.get(r.json()["midia_url"])).headers["content-type"] == "audio/webm"


async def test_tipo_invalido_415(client: httpx.AsyncClient) -> None:
    loja = await _loja(client)
    r = await client.post(f"/webchat/{loja}/midias", files=_arquivo(b"<html>", "text/html"))
    assert r.status_code == 415
    assert r.json()["erros"][0]["caminho"] == "arquivo"


async def test_arquivo_grande_demais_413(client: httpx.AsyncClient) -> None:
    loja = await _loja(client)
    r = await client.post(
        f"/webchat/{loja}/midias", files=_arquivo(b"0" * (LIMITE + 1), "image/png")
    )
    assert r.status_code == 413


async def test_sem_arquivo_422(client: httpx.AsyncClient) -> None:
    loja = await _loja(client)
    assert (await client.post(f"/webchat/{loja}/midias")).status_code == 422


async def test_loja_inexistente_404(client: httpx.AsyncClient) -> None:
    r = await client.post(f"/webchat/{uuid4()}/midias", files=_arquivo(PNG, "image/png"))
    assert r.status_code == 404


async def test_midia_inexistente_ou_traversal_404(client: httpx.AsyncClient) -> None:
    assert (await client.get("/midias/nao-existe.png")).status_code == 404
    assert (await client.get("/midias/..%2f..%2fetc%2fpasswd")).status_code == 404


async def test_midia_url_aceita_na_mensagem(client: httpx.AsyncClient) -> None:
    from app.adapters.outbound.barramento.memoria import BarramentoEmMemoria
    from app.infra.dependencias import get_agendar, get_barramento

    async def agendar(_: object) -> None:
        return None

    app.dependency_overrides[get_barramento] = lambda: BarramentoEmMemoria()
    app.dependency_overrides[get_agendar] = lambda: agendar
    loja = await _loja(client)
    sessao = (await client.post(f"/webchat/{loja}/sessoes")).json()["sessao"]
    url = (await client.post(f"/webchat/{loja}/midias", files=_arquivo(PNG, "image/png"))).json()[
        "midia_url"
    ]
    r = await client.post(
        f"/webchat/{loja}/sessoes/{sessao}/mensagens",
        json={"id_cliente": "c1", "tipo": "imagem", "midia_url": url},
    )
    assert r.status_code == 202
