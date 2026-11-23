"""Isolamento por loja: sessao da loja A nunca enxerga lead/conversa/mensagem da loja B."""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.adapters.outbound.auth.hasher import HasherSenhaArgon2
from app.adapters.outbound.auth.usuarios import RepositorioUsuariosSql
from app.adapters.outbound.barramento.memoria import BarramentoEmMemoria
from app.adapters.outbound.db.config import RepositorioLojasSql
from app.adapters.outbound.db.models import Conversa, Lead, Mensagem
from app.application.auth.contas import CriarLojaComLogin
from app.application.auth.memoria import LimiteTentativasMemoria, MemoriaSessoes
from app.infra.dependencias import (
    get_agendar,
    get_barramento,
    get_limite_tentativas,
    get_session,
    get_sessoes,
)
from app.main import app
from tests.integration.conftest import aplicar_migrations
from tests.integration.lojas import criar_loja_no_banco

pytestmark = [pytest.mark.integration, pytest.mark.autenticacao_real]


class Ambiente:
    def __init__(self, client: httpx.AsyncClient, loja_a: str, loja_b: str, lead_b: UUID) -> None:
        self.client = client
        self.loja_a = loja_a
        self.loja_b = loja_b
        self.lead_b = lead_b


@pytest.fixture
async def amb(db_url: str) -> AsyncIterator[Ambiente]:
    await aplicar_migrations(db_url)
    engine = create_async_engine(db_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    sessoes = MemoriaSessoes()
    barramento = BarramentoEmMemoria()

    async def _sessao() -> AsyncIterator[AsyncSession]:
        async with factory() as s:
            try:
                yield s
            except BaseException:
                await s.rollback()
                raise

    async def _agendar(_: UUID) -> None:
        return None

    app.dependency_overrides[get_session] = _sessao
    app.dependency_overrides[get_sessoes] = lambda: sessoes
    app.dependency_overrides[get_barramento] = lambda: barramento
    app.dependency_overrides[get_agendar] = lambda: _agendar
    loja_a = await criar_loja_no_banco("Loja A")
    loja_b = await criar_loja_no_banco("Loja B")
    async with factory() as s:
        lead = Lead(loja_id=UUID(loja_b), telefone="s1", canal="webchat", etapa="novo_contato")
        s.add(lead)
        await s.flush()
        conversa = Conversa(loja_id=UUID(loja_b), lead_id=lead.id, canal="webchat")
        s.add(conversa)
        await s.flush()
        s.add(
            Mensagem(
                loja_id=UUID(loja_b),
                conversa_id=conversa.id,
                canal="webchat",
                direcao="entrada",
                autor="cliente",
                tipo="texto",
                conteudo="segredo da loja B",
            )
        )
        await s.commit()
        lead_b = lead.id
    token_a = await sessoes.criar(uuid4(), UUID(loja_a))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://t", cookies={"sessao": token_a}
    ) as c:
        yield Ambiente(c, loja_a, loja_b, lead_b)
    app.dependency_overrides.clear()
    await engine.dispose()


async def test_detalhe_do_lead_de_outra_loja_e_404(amb: Ambiente) -> None:
    r = await amb.client.get(f"/lojas/{amb.loja_a}/leads/{amb.lead_b}")
    assert r.status_code == 404
    assert "segredo" not in r.text


@pytest.mark.parametrize(
    ("caminho", "corpo"),
    [
        ("etapa", {"etapa": "interesse_qualificado"}),
        ("assumir", {"vendedor_id": str(uuid4())}),
        ("devolver", None),
        ("mensagens", {"texto": "oi"}),
    ],
)
async def test_acoes_no_lead_de_outra_loja_sao_404(
    amb: Ambiente, caminho: str, corpo: dict[str, str] | None
) -> None:
    r = await amb.client.post(f"/lojas/{amb.loja_a}/leads/{amb.lead_b}/{caminho}", json=corpo)
    assert r.status_code == 404, r.text


async def test_kanban_da_loja_a_nao_traz_leads_da_b(amb: Ambiente) -> None:
    r = await amb.client.get(f"/lojas/{amb.loja_a}/leads")
    assert r.status_code == 200
    assert str(amb.lead_b) not in r.text


async def test_usar_o_id_da_loja_b_com_sessao_da_a_e_403(amb: Ambiente) -> None:
    r = await amb.client.get(f"/lojas/{amb.loja_b}/leads/{amb.lead_b}")
    assert r.status_code == 403
    assert "segredo" not in r.text


# --- duas lojas criadas com `CriarLojaComLogin`, cada uma logada pelo `POST /auth/login` ---------

SENHA_A = "senha-da-loja-a-123"
SENHA_B = "senha-da-loja-b-456"
PERFIL = {"nome_exibicao": "Loja Perfil", "responder_em_audio": True}
PRECO: dict[str, object] = {
    "max_parcelas": 12,
    "repassa_taxa": True,
    "desconto_pix_tipo": "percentual",
    "desconto_pix_valor": "5",
    "aceita_entrada_mais_cartao": True,
    "desconto_teto": "100",
    "desconto_degrau": "50",
    "oportunidade_ativa": False,
    "oportunidade_dias_minimos": 14,
    "oportunidade_valor": "100",
    "oportunidade_conta_no_teto": False,
}


class DuasLojas:
    def __init__(
        self, cliente_a: httpx.AsyncClient, cliente_b: httpx.AsyncClient, loja_a: UUID, loja_b: UUID
    ) -> None:
        self.a = cliente_a
        self.b = cliente_b
        self.loja_a = loja_a
        self.loja_b = loja_b


@pytest.fixture
async def duas(db_url: str) -> AsyncIterator[DuasLojas]:
    await aplicar_migrations(db_url)
    engine = create_async_engine(db_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    sessoes = MemoriaSessoes()
    limite = LimiteTentativasMemoria(janela_s=60)
    barramento = BarramentoEmMemoria()

    async def _sessao() -> AsyncIterator[AsyncSession]:
        async with factory() as s:
            try:
                yield s
            except BaseException:
                await s.rollback()
                raise

    async def _agendar(_: UUID) -> None:
        return None

    app.dependency_overrides[get_session] = _sessao
    app.dependency_overrides[get_sessoes] = lambda: sessoes
    app.dependency_overrides[get_limite_tentativas] = lambda: limite
    app.dependency_overrides[get_barramento] = lambda: barramento
    app.dependency_overrides[get_agendar] = lambda: _agendar
    hasher = HasherSenhaArgon2()
    ids: list[UUID] = []
    for nome, email, senha in (
        ("Loja A", "dono-a@loja.com", SENHA_A),
        ("Loja B", "dono-b@loja.com", SENHA_B),
    ):
        async with factory() as s:
            criar = CriarLojaComLogin(
                RepositorioLojasSql(s).criar, RepositorioUsuariosSql(s), hasher
            )
            conta = await criar(nome, email, senha)
            await s.commit()
            ids.append(conta.loja_id)
    transport = httpx.ASGITransport(app=app)
    async with (
        httpx.AsyncClient(transport=transport, base_url="http://t") as a,
        httpx.AsyncClient(transport=transport, base_url="http://t") as b,
    ):
        for cliente, email, senha in (
            (a, "dono-a@loja.com", SENHA_A),
            (b, "dono-b@loja.com", SENHA_B),
        ):
            r = await cliente.post("/auth/login", json={"email": email, "senha": senha})
            assert r.status_code == 200, r.text
        yield DuasLojas(a, b, ids[0], ids[1])
    app.dependency_overrides.clear()
    await engine.dispose()


async def test_login_real_leva_cada_uma_para_a_propria_loja(duas: DuasLojas) -> None:
    assert (await duas.a.get("/auth/eu")).json()["loja_id"] == str(duas.loja_a)
    assert (await duas.b.get("/auth/eu")).json()["loja_id"] == str(duas.loja_b)


async def test_config_da_outra_loja_nao_le_nem_altera(duas: DuasLojas) -> None:
    # B grava o proprio perfil e preco; A so enxerga 403, e nada muda para B.
    assert (await duas.b.put(f"/lojas/{duas.loja_b}/config/perfil", json=PERFIL)).status_code == 200
    assert (await duas.b.put(f"/lojas/{duas.loja_b}/config/preco", json=PRECO)).status_code == 200

    for caminho in ("perfil", "preco"):
        r = await duas.a.get(f"/lojas/{duas.loja_b}/config/{caminho}")
        assert r.status_code == 403, caminho
        assert "Loja Perfil" not in r.text
    r = await duas.a.put(f"/lojas/{duas.loja_b}/config/perfil", json={"nome_exibicao": "Invadida"})
    assert r.status_code == 403
    r = await duas.a.put(f"/lojas/{duas.loja_b}/config/preco", json={**PRECO, "max_parcelas": 3})
    assert r.status_code == 403

    perfil_b = (await duas.b.get(f"/lojas/{duas.loja_b}/config/perfil")).json()
    assert perfil_b["nome_exibicao"] == "Loja Perfil"
    assert (await duas.b.get(f"/lojas/{duas.loja_b}/config/preco")).json()["max_parcelas"] == 12
    # A continua sem config e sem vazamento da B
    assert (await duas.a.get(f"/lojas/{duas.loja_a}/config/perfil")).json() is None


async def test_metricas_da_outra_loja_e_403(duas: DuasLojas) -> None:
    assert (await duas.b.get(f"/lojas/{duas.loja_b}/metricas")).status_code == 200
    assert (await duas.a.get(f"/lojas/{duas.loja_a}/metricas")).status_code == 200
    assert (await duas.a.get(f"/lojas/{duas.loja_b}/metricas")).status_code == 403


async def test_eventos_sse_da_outra_loja_e_403_e_sem_sessao_401(duas: DuasLojas) -> None:
    r = await duas.a.get(f"/lojas/{duas.loja_b}/eventos")
    assert r.status_code == 403
    assert "text/event-stream" not in r.headers.get("content-type", "")
    anonimo = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")
    async with anonimo:
        assert (await anonimo.get(f"/lojas/{duas.loja_b}/eventos")).status_code == 401


async def test_webchat_publico_de_cada_loja_funciona_sem_cookie(duas: DuasLojas) -> None:
    transport = httpx.ASGITransport(app=app)
    for loja in (duas.loja_a, duas.loja_b):
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as anonimo:
            r = await anonimo.post(f"/webchat/{loja}/sessoes")
            assert r.status_code == 201, r.text
            sessao = r.json()["sessao"]
            r = await anonimo.post(
                f"/webchat/{loja}/sessoes/{sessao}/mensagens",
                json={"id_cliente": "m1", "tipo": "texto", "texto": "oi"},
            )
            assert r.status_code == 202, r.text
            assert not anonimo.cookies

    # a mensagem entrou como lead da loja certa: cada painel ve so o seu
    leads_a = (await duas.a.get(f"/lojas/{duas.loja_a}/leads")).text
    leads_b = (await duas.b.get(f"/lojas/{duas.loja_b}/leads")).text
    assert "oi" in leads_a or "webchat" in leads_a
    assert leads_a != leads_b
