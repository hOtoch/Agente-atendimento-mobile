"""Isolamento por loja: sessao da loja A nunca enxerga lead/conversa/mensagem da loja B."""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.adapters.outbound.barramento.memoria import BarramentoEmMemoria
from app.adapters.outbound.db.models import Conversa, Lead, Mensagem
from app.application.auth.memoria import MemoriaSessoes
from app.infra.dependencias import get_agendar, get_barramento, get_session, get_sessoes
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
