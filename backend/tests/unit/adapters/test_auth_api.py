"""Rotas /auth com fakes em memoria (sem banco nem Redis)."""

from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

import httpx
import pytest

from app.application.auth.memoria import MemoriaSessoes, MemoriaUsuarios, SenhaSemHash
from app.infra.dependencias import (
    get_hasher_senha,
    get_repositorio_usuarios,
    get_session,
    get_sessoes,
)
from app.infra.settings import Settings, get_settings
from app.main import app

SENHA = "senha-segura-123"

Ambiente = tuple[httpx.AsyncClient, MemoriaUsuarios, MemoriaSessoes]


class SessaoFalsa:
    async def commit(self) -> None:
        return None


@pytest.fixture
async def ambiente() -> AsyncIterator[Ambiente]:
    usuarios, sessoes, hasher = MemoriaUsuarios(), MemoriaSessoes(), SenhaSemHash()
    loja = uuid4()
    usuarios.adicionar_loja(loja, "Loja Demo")
    usuarios.adicionar(loja, "dono@loja.com", await hasher.gerar(SENHA), senha_provisoria=True)

    async def _sessao() -> AsyncIterator[SessaoFalsa]:
        yield SessaoFalsa()

    app.dependency_overrides[get_session] = _sessao
    app.dependency_overrides[get_repositorio_usuarios] = lambda: usuarios
    app.dependency_overrides[get_sessoes] = lambda: sessoes
    app.dependency_overrides[get_hasher_senha] = lambda: hasher
    app.dependency_overrides[get_settings] = lambda: Settings(
        sessao_ttl_horas=2, cookie_secure=True
    )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://t") as c:
        yield c, usuarios, sessoes
    app.dependency_overrides.clear()


async def _login(c: httpx.AsyncClient, senha: str = SENHA) -> httpx.Response:
    return await c.post("/auth/login", json={"email": "Dono@loja.com", "senha": senha})


async def test_login_certo_devolve_cookie_e_corpo(ambiente: Ambiente) -> None:
    c, _, _ = ambiente
    r = await _login(c)
    assert r.status_code == 200
    corpo = r.json()
    assert corpo["loja_nome"] == "Loja Demo" and corpo["email"] == "dono@loja.com"
    assert corpo["senha_provisoria"] is True and corpo["loja_id"]
    cookie = r.headers["set-cookie"].lower()
    assert cookie.startswith("sessao=")
    for parte in ("httponly", "samesite=lax", "path=/", "max-age=7200", "secure"):
        assert parte in cookie, cookie
    assert (await c.get("/auth/eu")).json() == corpo


async def test_cookie_sem_secure_quando_configurado(ambiente: Ambiente) -> None:
    c, _, _ = ambiente
    app.dependency_overrides[get_settings] = lambda: Settings(cookie_secure=False)
    r = await _login(c)
    assert "secure" not in r.headers["set-cookie"].lower()


async def test_credencial_invalida_e_o_mesmo_401(ambiente: Ambiente) -> None:
    c, usuarios, _ = ambiente
    r1 = await c.post("/auth/login", json={"email": "x@y.com", "senha": SENHA})
    r2 = await _login(c, "errada-errada")
    usuarios.desativar(next(iter(usuarios.por_id)))
    r3 = await _login(c)
    assert {r.status_code for r in (r1, r2, r3)} == {401}
    assert r1.json() == r2.json() == r3.json()
    assert "set-cookie" not in r1.headers


async def test_eu_sem_cookie_ou_com_cookie_falso_da_401(ambiente: Ambiente) -> None:
    c, _, _ = ambiente
    assert (await c.get("/auth/eu")).status_code == 401
    assert (await c.get("/auth/eu", cookies={"sessao": "falso"})).status_code == 401


async def test_logout_invalida_o_cookie_antigo(ambiente: Ambiente) -> None:
    c, _, _ = ambiente
    token = (await _login(c)).cookies["sessao"]
    r = await c.post("/auth/logout")
    assert r.status_code == 204
    assert "max-age=0" in r.headers["set-cookie"].lower()
    assert (await c.get("/auth/eu", cookies={"sessao": token})).status_code == 401


async def test_logout_sem_sessao_da_204(ambiente: Ambiente) -> None:
    c, _, _ = ambiente
    assert (await c.post("/auth/logout")).status_code == 204


async def test_trocar_senha(ambiente: Ambiente) -> None:
    c, _, sessoes = ambiente
    await _login(c)
    primeira = c.cookies["sessao"]
    await _login(c)  # segunda sessao: o cookie do cliente passa a ser a dela
    token = c.cookies["sessao"]
    r = await c.put("/auth/senha", json={"senha_atual": SENHA, "senha_nova": "nova-senha-forte"})
    assert r.status_code == 204
    assert sessoes.ativos() == 1
    assert (await sessoes.obter(primeira)) is None
    assert (await sessoes.obter(token)) is not None
    assert (await c.get("/auth/eu")).json()["senha_provisoria"] is False


@pytest.mark.parametrize(
    ("atual", "nova", "motivo"),
    [
        ("errada-errada", "nova-senha-forte", "senha_atual_incorreta"),
        (SENHA, "curta", "senha_nova_curta"),
        (SENHA, SENHA, "senha_nova_igual"),
    ],
)
async def test_trocar_senha_recusada_da_400_com_motivo(
    ambiente: Ambiente, atual: str, nova: str, motivo: str
) -> None:
    c, _, _ = ambiente
    await _login(c)
    r = await c.put("/auth/senha", json={"senha_atual": atual, "senha_nova": nova})
    assert r.status_code == 400
    body: dict[str, Any] = r.json()
    assert body["motivo"] == motivo


async def test_trocar_senha_sem_sessao_da_401(ambiente: Ambiente) -> None:
    c, _, _ = ambiente
    r = await c.put("/auth/senha", json={"senha_atual": SENHA, "senha_nova": "nova-senha-forte"})
    assert r.status_code == 401
