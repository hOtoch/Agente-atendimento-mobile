"""`scripts/popular_metricas_demo.py` contra um banco de teste isolado (modo de teste)."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.adapters.outbound.db.config import RepositorioLojasSql
from app.adapters.outbound.db.metricas import LeitorMetricasSql
from app.adapters.outbound.db.models import Conversa, Evento, Lead, Loja, Mensagem
from app.application.metricas import MetricasAgente
from app.domain.metricas import FUSO
from app.infra.dependencias import get_session
from app.main import app
from tests.integration.conftest import aplicar_migrations
from tests.unit.scripts.test_popular_metricas_demo import carregar_popular

pytestmark = pytest.mark.integration

demo = carregar_popular()

AGORA = datetime(2026, 11, 22, 15, 0, tzinfo=FUSO)
HOJE = AGORA.date()
DIAS = 30
SONNET = "claude-sonnet-5-5"
TABELAS = ("leads", "conversas", "mensagens", "eventos")


@pytest.fixture
async def banco(db_url: str) -> AsyncIterator[tuple[str, async_sessionmaker[AsyncSession]]]:
    await aplicar_migrations(db_url)
    engine = create_async_engine(db_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield db_url, factory
    await engine.dispose()


async def _loja(factory: async_sessionmaker[AsyncSession]) -> uuid.UUID:
    loja_id = uuid.uuid4()
    async with factory() as s:
        s.add(Loja(id=loja_id, nome="Loja demo de teste"))
        await s.commit()
    return loja_id


async def _contagens(
    factory: async_sessionmaker[AsyncSession], loja_id: uuid.UUID
) -> dict[str, int]:
    async with factory() as s:
        return {
            t: (
                await s.execute(
                    text(f"SELECT count(*) FROM {t} WHERE loja_id = :l"),  # noqa: S608
                    {"l": loja_id},
                )
            ).scalar_one()
            for t in TABELAS
        }


async def _real(factory: async_sessionmaker[AsyncSession], loja_id: uuid.UUID) -> None:
    """Um atendimento de verdade (nada de demonstracao) que o script nunca pode tocar."""
    async with factory() as s:
        lead = Lead(
            loja_id=loja_id, telefone="5511988887777", canal="whatsapp", nome="Cliente real"
        )
        s.add(lead)
        await s.flush()
        conversa = Conversa(loja_id=loja_id, lead_id=lead.id, canal="whatsapp")
        s.add(conversa)
        await s.flush()
        s.add(
            Mensagem(
                loja_id=loja_id,
                conversa_id=conversa.id,
                canal="whatsapp",
                direcao="entrada",
                autor="cliente",
                conteudo="oi",
            )
        )
        s.add(Evento(loja_id=loja_id, lead_id=lead.id, tipo="llm_uso", payload={"modelo": SONNET}))
        s.add(Evento(loja_id=loja_id, tipo="ferramenta", payload={"demo": False, "nome": "x"}))
        await s.commit()


async def _metricas(factory: async_sessionmaker[AsyncSession], loja_id: uuid.UUID) -> Any:
    async with factory() as s:
        caso = MetricasAgente(RepositorioLojasSql(s), LeitorMetricasSql(s), hoje=lambda: HOJE)
        return await caso.executar(loja_id)


async def test_popular_enche_todos_os_dias_com_kpis_coerentes(banco) -> None:  # type: ignore[no-untyped-def]
    url, factory = banco
    loja = await _loja(factory)
    resumo = await demo.popular(url, loja, DIAS, seed=7, agora=AGORA, permitir_teste=True)
    assert resumo.leads > 100 and resumo.mensagens > resumo.leads

    m = await _metricas(factory, loja)
    assert len(m.series) == DIAS
    for p in m.series:
        assert p.conversas_novas > 0, p.dia
        assert p.conversas_ativas > 0, p.dia
        assert p.mensagens_recebidas > 0, p.dia
        assert p.tokens > 0 and p.custo_usd > 0, p.dia
        assert p.tempo_resposta_media_ms is not None, p.dia
    k = m.kpis
    assert k.custo_total_usd.valor is not None and k.custo_total_usd.valor > 0
    assert m.custo.completo is True and m.custo.modelos_sem_preco == ()
    assert k.latencia_llm_media_ms.valor is not None and k.latencia_llm_p95_ms.valor is not None
    assert k.tempo_resposta_p95_ms.valor is not None
    assert k.tempo_resposta_media_ms.valor > k.latencia_llm_media_ms.valor  # inclui o debounce
    assert k.taxa_cache.valor is not None and k.taxa_cache.valor > 0
    # handoffs por categoria: todas as tres principais aparecem
    por = {h.motivo: h.quantidade for h in m.handoffs}
    assert por["pedido_cliente"] > 0 and por["acordo_fechado"] > 0 and por["falha_tecnica"] > 0
    assert m.total_handoffs == sum(por.values())
    # funil com varias etapas e acordos coerentes com os handoffs de acordo
    assert sum(1 for e in m.funil if e.leads > 0) >= 4
    assert k.acordos_fechados.valor is not None and k.acordos_fechados.valor > 0
    assert k.acordos_fechados.valor == por["acordo_fechado"]  # um acordo por handoff de acordo
    # erros: LLM, ferramentas, limite de iteracoes e respostas descartadas
    assert m.erros.llm > 0 and m.erros.ferramentas > 0
    assert m.erros.limite_iteracoes > 0 and m.erros.respostas_descartadas > 0
    assert m.erros.total < m.tokens.chamadas  # poucos erros
    assert {f.nome for f in m.ferramentas} >= {"consultar_estoque", "calcular_proposta"}
    assert len(m.modelos_procurados) > 3
    # picos de fim da manha e noite; domingo mais fraco
    horas = {h: 0 for h in range(24)}
    dias = {d: 0 for d in range(7)}
    for c in m.mapa_horario:
        horas[c.hora] += c.mensagens
        dias[c.dia_semana] += c.mensagens
    assert horas[12] > horas[3] * 5 and horas[20] > horas[3] * 5
    assert dias[6] < min(dias[d] for d in range(5))


async def test_pelo_endpoint_metricas_tem_dados_em_todos_os_dias(banco) -> None:  # type: ignore[no-untyped-def]
    url, factory = banco
    loja = await _loja(factory)
    await demo.popular(url, loja, DIAS, seed=3, agora=AGORA, permitir_teste=True)

    async def _sessao() -> AsyncIterator[AsyncSession]:
        async with factory() as s:
            yield s

    app.dependency_overrides[get_session] = _sessao
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://t"
        ) as http:
            r = await http.get(
                f"/lojas/{loja}/metricas",
                params={"de": str(HOJE - timedelta(days=DIAS - 1)), "ate": str(HOJE)},
            )
    finally:
        app.dependency_overrides.clear()
    assert r.status_code == 200
    corpo = r.json()
    assert len(corpo["series"]) == DIAS
    assert all(p["conversas_ativas"] > 0 and p["tokens"] > 0 for p in corpo["series"])
    assert float(corpo["kpis"]["custo_total_usd"]["valor"]) > 0
    assert any(h["quantidade"] > 0 for h in corpo["handoffs"]["por_motivo"])


async def test_nada_no_futuro_e_tudo_marcado_como_demonstracao(banco) -> None:  # type: ignore[no-untyped-def]
    url, factory = banco
    loja = await _loja(factory)
    await demo.popular(url, loja, 5, seed=1, agora=AGORA, permitir_teste=True)
    async with factory() as s:
        futuros = (
            await s.execute(
                text(
                    "SELECT (SELECT count(*) FROM eventos WHERE criado_em > :a)"
                    " + (SELECT count(*) FROM mensagens WHERE criado_em > :a)"
                    " + (SELECT count(*) FROM leads WHERE criado_em > :a)"
                ),
                {"a": AGORA.astimezone(UTC)},
            )
        ).scalar_one()
        sem_marca = (
            await s.execute(
                text(
                    "SELECT count(*) FROM eventos WHERE loja_id = :l"
                    " AND coalesce(payload->>'demo', '') <> 'true'"
                ),
                {"l": loja},
            )
        ).scalar_one()
        leads_fora = (
            await s.execute(
                text(
                    "SELECT count(*) FROM leads WHERE loja_id = :l AND telefone NOT LIKE 'demo:%'"
                ),
                {"l": loja},
            )
        ).scalar_one()
    assert futuros == 0
    assert sem_marca == 0
    assert leads_fora == 0


async def test_remover_deixa_o_banco_como_antes_e_preserva_o_que_nao_e_demo(banco) -> None:  # type: ignore[no-untyped-def]
    url, factory = banco
    loja = await _loja(factory)
    await _real(factory, loja)
    antes = await _contagens(factory, loja)
    assert antes == {"leads": 1, "conversas": 1, "mensagens": 1, "eventos": 2}

    criado = await demo.popular(url, loja, 10, seed=5, agora=AGORA, permitir_teste=True)
    meio = await _contagens(factory, loja)
    assert meio["leads"] == 1 + criado.leads
    assert meio["mensagens"] == 1 + criado.mensagens
    assert meio["eventos"] == 2 + criado.eventos

    removido = await demo.remover(url, loja, permitir_teste=True)
    assert (removido.leads, removido.mensagens, removido.eventos) == (
        criado.leads,
        criado.mensagens,
        criado.eventos,
    )
    assert await _contagens(factory, loja) == antes
    async with factory() as s:
        nome = (
            await s.execute(text("SELECT nome FROM leads WHERE loja_id = :l"), {"l": loja})
        ).scalar_one()
    assert nome == "Cliente real"

    de_novo = await demo.remover(url, loja, permitir_teste=True)
    assert (de_novo.leads, de_novo.mensagens, de_novo.eventos) == (0, 0, 0)


async def test_remover_so_mexe_na_loja_indicada(banco) -> None:  # type: ignore[no-untyped-def]
    url, factory = banco
    a, b = await _loja(factory), await _loja(factory)
    await demo.popular(url, a, 5, seed=2, agora=AGORA, permitir_teste=True)
    await demo.popular(url, b, 5, seed=2, agora=AGORA, permitir_teste=True)
    antes_b = await _contagens(factory, b)
    await demo.remover(url, a, permitir_teste=True)
    assert await _contagens(factory, a) == dict.fromkeys(TABELAS, 0)
    assert await _contagens(factory, b) == antes_b


async def test_idempotente_e_deterministico_com_seed(banco) -> None:  # type: ignore[no-untyped-def]
    url, factory = banco
    loja = await _loja(factory)
    primeira = await demo.popular(url, loja, DIAS, seed=11, agora=AGORA, permitir_teste=True)
    apos_primeira = await _contagens(factory, loja)
    m1 = await _metricas(factory, loja)

    segunda = await demo.popular(url, loja, DIAS, seed=11, agora=AGORA, permitir_teste=True)
    assert await _contagens(factory, loja) == apos_primeira  # nao duplicou
    assert segunda == primeira  # mesmo seed, mesmo resultado
    m2 = await _metricas(factory, loja)
    assert m2.kpis == m1.kpis and m2.series == m1.series

    outra = await demo.popular(url, loja, DIAS, seed=12, agora=AGORA, permitir_teste=True)
    assert outra != primeira
    leads = (await _contagens(factory, loja))["leads"]
    assert leads == outra.leads  # so os da ultima execucao


async def test_mudar_os_dias_substitui_o_periodo_anterior(banco) -> None:  # type: ignore[no-untyped-def]
    url, factory = banco
    loja = await _loja(factory)
    await demo.popular(url, loja, 60, seed=1, agora=AGORA, permitir_teste=True)
    curto = await demo.popular(url, loja, 10, seed=1, agora=AGORA, permitir_teste=True)
    assert (await _contagens(factory, loja))["leads"] == curto.leads
    m = await _metricas(factory, loja)
    assert m.kpis.conversas_ativas.anterior == 0  # os 30 dias anteriores ficaram vazios


async def test_loja_inexistente_e_recusada_sem_criar_nada(banco) -> None:  # type: ignore[no-untyped-def]
    url, factory = banco
    with pytest.raises(demo.LojaNaoEncontrada):
        await demo.popular(url, uuid.uuid4(), 5, seed=1, agora=AGORA, permitir_teste=True)
    async with factory() as s:
        n = (await s.execute(text("SELECT count(*) FROM leads"))).scalar_one()
    assert n == 0


async def test_recusa_banco_de_teste_sem_o_modo_de_teste(banco) -> None:  # type: ignore[no-untyped-def]
    url, factory = banco
    loja = await _loja(factory)
    with pytest.raises(demo.BancoInseguro):
        await demo.popular(url, loja, 5, seed=1, agora=AGORA)
    with pytest.raises(demo.BancoInseguro):
        await demo.remover(url, loja)
    assert (await _contagens(factory, loja))["leads"] == 0


async def test_usa_vendedores_da_propria_loja(banco) -> None:  # type: ignore[no-untyped-def]
    from app.adapters.outbound.db.models import Vendedor

    url, factory = banco
    loja = await _loja(factory)
    async with factory() as s:
        vendedor = Vendedor(loja_id=loja, nome="Vendedor teste")
        s.add(vendedor)
        await s.commit()
        vendedor_id = vendedor.id
    await demo.popular(url, loja, 10, seed=4, agora=AGORA, permitir_teste=True)
    async with factory() as s:
        ids = (
            (
                await s.execute(
                    text(
                        "SELECT DISTINCT vendedor_id FROM leads "
                        "WHERE loja_id = :l AND dono = 'vendedor'"
                    ),
                    {"l": loja},
                )
            )
            .scalars()
            .all()
        )
    assert ids == [vendedor_id]
    await demo.remover(url, loja, permitir_teste=True)
    async with factory() as s:
        assert (
            await s.execute(text("SELECT count(*) FROM vendedores WHERE loja_id = :l"), {"l": loja})
        ).scalar_one() == 1


def test_data_de_referencia_do_teste() -> None:
    assert date(2026, 11, 22) == HOJE and HOJE.weekday() == 6  # domingo
