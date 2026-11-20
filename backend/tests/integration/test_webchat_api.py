"""API do webchat com o app real e Postgres isolado; barramento em memoria."""

import asyncio
import json
from collections.abc import AsyncIterator
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.adapters.outbound.barramento.memoria import BarramentoEmMemoria
from app.adapters.outbound.canal.webchat import WebChatAdapter, topico_webchat
from app.adapters.outbound.db.models import Mensagem
from app.application.canal import Canal, MensagemSaida, TipoMensagem
from app.infra.dependencias import get_agendar, get_barramento, get_session
from app.main import app
from tests.integration.conftest import aplicar_migrations

pytestmark = pytest.mark.integration


class Ambiente:
    def __init__(
        self,
        client: httpx.AsyncClient,
        barramento: BarramentoEmMemoria,
        factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self.client = client
        self.barramento = barramento
        self.factory = factory
        self.agendadas: list[UUID] = []


@pytest.fixture
async def amb(db_url: str) -> AsyncIterator[Ambiente]:
    await aplicar_migrations(db_url)
    engine = create_async_engine(db_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    barramento = BarramentoEmMemoria()

    async def _sessao() -> AsyncIterator[AsyncSession]:
        async with factory() as s:
            try:
                yield s
            except BaseException:
                await s.rollback()
                raise

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        a = Ambiente(c, barramento, factory)

        async def agendar(conversa_id: UUID) -> None:
            a.agendadas.append(conversa_id)

        app.dependency_overrides[get_session] = _sessao
        app.dependency_overrides[get_barramento] = lambda: barramento
        app.dependency_overrides[get_agendar] = lambda: agendar
        yield a
    app.dependency_overrides.clear()
    await engine.dispose()


async def _loja(c: httpx.AsyncClient) -> str:
    r = await c.post("/lojas", json={"nome": "Loja Web"})
    return str(r.json()["id"])


async def _sessao_web(c: httpx.AsyncClient, loja: str) -> str:
    r = await c.post(f"/webchat/{loja}/sessoes")
    assert r.status_code == 201
    return str(r.json()["sessao"])


def _corpo(id_cliente: str = "c1", texto: str = "oi") -> dict[str, object]:
    return {"id_cliente": id_cliente, "tipo": "texto", "texto": texto}


async def test_cria_sessao_uuid(amb: Ambiente) -> None:
    loja = await _loja(amb.client)
    UUID(await _sessao_web(amb.client, loja))


async def test_loja_inexistente_404(amb: Ambiente) -> None:
    ghost = uuid4()
    assert (await amb.client.post(f"/webchat/{ghost}/sessoes")).status_code == 404
    r = await amb.client.post(f"/webchat/{ghost}/sessoes/abc/mensagens", json=_corpo())
    assert r.status_code == 404
    assert (await amb.client.get(f"/webchat/{ghost}/sessoes/abc/stream")).status_code == 404


async def test_post_persiste_agenda_e_responde_202(amb: Ambiente) -> None:
    loja = await _loja(amb.client)
    sessao = await _sessao_web(amb.client, loja)
    r = await amb.client.post(f"/webchat/{loja}/sessoes/{sessao}/mensagens", json=_corpo())
    assert r.status_code == 202
    corpo = r.json()
    assert corpo["nova"] is True
    assert amb.agendadas == [UUID(corpo["conversa_id"])]
    async with amb.factory() as s:
        total = (await s.execute(select(func.count()).select_from(Mensagem))).scalar_one()
    assert total == 1


async def test_mesmo_id_cliente_nao_duplica_nem_reagenda(amb: Ambiente) -> None:
    loja = await _loja(amb.client)
    sessao = await _sessao_web(amb.client, loja)
    url = f"/webchat/{loja}/sessoes/{sessao}/mensagens"
    r1 = await amb.client.post(url, json=_corpo())
    r2 = await amb.client.post(url, json=_corpo())
    assert r2.status_code == 202
    assert r2.json() == {"conversa_id": r1.json()["conversa_id"], "nova": False}
    assert len(amb.agendadas) == 1


async def test_texto_obrigatorio_para_tipo_texto(amb: Ambiente) -> None:
    loja = await _loja(amb.client)
    sessao = await _sessao_web(amb.client, loja)
    r = await amb.client.post(
        f"/webchat/{loja}/sessoes/{sessao}/mensagens",
        json={"id_cliente": "c1", "tipo": "texto"},
    )
    assert r.status_code == 422


async def test_sse_entrega_mensagem_publicada(amb: Ambiente) -> None:
    loja = await _loja(amb.client)
    sessao = await _sessao_web(amb.client, loja)
    topico = topico_webchat(UUID(loja), sessao)

    async def ler() -> list[str]:
        linhas: list[str] = []
        async with amb.client.stream("GET", f"/webchat/{loja}/sessoes/{sessao}/stream") as r:
            assert r.status_code == 200
            assert r.headers["content-type"].startswith("text/event-stream")
            async for linha in r.aiter_lines():
                linhas.append(linha)
        return linhas

    # ASGITransport so entrega o corpo quando a resposta termina: o teste publica e
    # depois fecha o topico (BarramentoEmMemoria.fechar), o que encerra o stream.
    tarefa = asyncio.create_task(ler())
    await asyncio.sleep(0.3)
    await WebChatAdapter(amb.barramento).enviar(
        MensagemSaida(
            loja_id=UUID(loja),
            canal=Canal.WEBCHAT,
            destinatario=sessao,
            tipo=TipoMensagem.TEXTO,
            texto="resposta",
            midia_url=None,
        )
    )
    amb.barramento.fechar(topico)
    linhas = await asyncio.wait_for(tarefa, 5)
    dados = [json.loads(linha[5:]) for linha in linhas if linha.startswith("data:")]
    assert dados[0]["texto"] == "resposta"


async def test_primeira_mensagem_cria_lead_em_novo_contato_no_kanban(amb: Ambiente) -> None:
    loja = await _loja(amb.client)
    sessao = await _sessao_web(amb.client, loja)
    antes = (await amb.client.get(f"/lojas/{loja}/leads")).json()["etapas"]
    assert all(e["leads"] == [] for e in antes)

    r = await amb.client.post(f"/webchat/{loja}/sessoes/{sessao}/mensagens", json=_corpo())
    assert r.status_code == 202

    etapas = (await amb.client.get(f"/lojas/{loja}/leads")).json()["etapas"]
    novo = next(e for e in etapas if e["etapa"] == "novo_contato")
    assert len(novo["leads"]) == 1
    assert novo["leads"][0]["canal"] == "webchat"
    assert novo["leads"][0]["telefone"] == sessao
