"""Varredura: nenhuma rota de loja nasce aberta; as publicas sao uma lista explicita.

Percorre o OpenAPI do app (nao as estruturas internas do FastAPI) e chama cada rota com
`{loja_id}` sem cookie (401) e com a sessao de outra loja (403).
"""

from collections.abc import AsyncIterator
from uuid import uuid4

import httpx
import pytest

from app.application.auth.memoria import MemoriaSessoes
from app.infra.dependencias import get_session, get_sessoes
from app.main import app

pytestmark = pytest.mark.autenticacao_real

METODOS = ("get", "post", "put", "patch", "delete")
# Rotas com `{loja_id}` no caminho que continuam publicas (cliente final no webchat).
PUBLICAS_COM_LOJA = ("/webchat/{loja_id}/",)
ID = "00000000-0000-0000-0000-000000000001"


def _rotas_de_loja() -> list[tuple[str, str]]:
    caminhos: dict[str, dict[str, object]] = app.openapi()["paths"]
    return sorted(
        (metodo.upper(), caminho)
        for caminho, operacoes in caminhos.items()
        if "{loja_id}" in caminho and not caminho.startswith(PUBLICAS_COM_LOJA)
        for metodo in operacoes
        if metodo in METODOS
    )


def _url(caminho: str) -> str:
    partes = caminho.replace("{loja_id}", ID).split("{")
    return "".join(p if i == 0 else ID + p.split("}", 1)[1] for i, p in enumerate(partes))


@pytest.fixture
async def cliente() -> AsyncIterator[tuple[httpx.AsyncClient, MemoriaSessoes]]:
    sessoes = MemoriaSessoes()
    app.dependency_overrides[get_sessoes] = lambda: sessoes
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        yield c, sessoes
    app.dependency_overrides.clear()


def test_a_lista_de_rotas_de_loja_nao_esta_vazia() -> None:
    rotas = _rotas_de_loja()
    assert len(rotas) > 30
    assert ("GET", "/lojas/{loja_id}/eventos") in rotas
    assert ("POST", "/lojas/{loja_id}/whatsapp/conectar") in rotas


def test_post_lojas_nao_existe_mais() -> None:
    assert "/lojas" not in app.openapi()["paths"]


@pytest.mark.parametrize(("metodo", "caminho"), _rotas_de_loja())
async def test_rota_de_loja_sem_cookie_e_401(
    cliente: tuple[httpx.AsyncClient, MemoriaSessoes], metodo: str, caminho: str
) -> None:
    c, _ = cliente
    r = await c.request(metodo, _url(caminho))
    assert r.status_code == 401, (metodo, caminho, r.text)


@pytest.mark.parametrize(("metodo", "caminho"), _rotas_de_loja())
async def test_rota_de_loja_com_sessao_de_outra_loja_e_403(
    cliente: tuple[httpx.AsyncClient, MemoriaSessoes], metodo: str, caminho: str
) -> None:
    c, sessoes = cliente
    token = await sessoes.criar(uuid4(), uuid4())
    c.cookies.set("sessao", token)
    r = await c.request(metodo, _url(caminho))
    assert r.status_code == 403, (metodo, caminho, r.text)


async def test_rotas_publicas_continuam_abertas(
    cliente: tuple[httpx.AsyncClient, MemoriaSessoes],
) -> None:
    c, _ = cliente
    assert (await c.get("/health")).status_code == 200
    # login sem corpo valido: 422 (chegou na rota, nao foi barrado por sessao)
    assert (await c.post("/auth/login", json={})).status_code == 422
    # webhook da Evolution: barrado pelo token proprio ("token do webhook invalido")
    r = await c.post("/webhooks/evolution", json={})
    assert r.status_code == 401 and "token" in r.json()["detail"]
    # modelo de planilha em branco e publico
    assert (await c.get("/modelos/vendedores")).status_code in (200, 422)
    # webchat: abrir sessao nao exige login. Teste unitario nao faz IO: o banco e trocado por
    # uma sessao que falha em qualquer uso; o que importa e nao ser barrado por sessao (401/403).
    app.dependency_overrides[get_session] = _sessao_sem_banco
    transporte = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transporte, base_url="http://t") as sem_cookie:
        r = await sem_cookie.post(f"/webchat/{ID}/sessoes")
    assert r.status_code not in (401, 403)


class _BancoIndisponivel:
    def __getattr__(self, nome: str) -> object:
        raise RuntimeError(f"teste unitario sem banco (tentou usar session.{nome})")


async def _sessao_sem_banco() -> AsyncIterator[_BancoIndisponivel]:
    yield _BancoIndisponivel()
