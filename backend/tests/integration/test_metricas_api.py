"""`GET /lojas/{id}/metricas`, com o app real e um banco de teste isolado."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.adapters.outbound.db.models import Conversa, Evento, Lead, Mensagem
from app.infra.dependencias import get_session
from app.main import app
from tests.integration.conftest import aplicar_migrations
from tests.integration.lojas import criar_loja_no_banco

pytestmark = pytest.mark.integration


@pytest.fixture
async def client(
    db_url: str,
) -> AsyncIterator[tuple[httpx.AsyncClient, async_sessionmaker[AsyncSession]]]:
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
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        yield c, factory
    app.dependency_overrides.clear()
    await engine.dispose()


async def _loja(client: httpx.AsyncClient) -> str:
    return await criar_loja_no_banco("Loja API")


async def test_padrao_sao_os_ultimos_30_dias_e_loja_vazia_devolve_zeros(client) -> None:  # type: ignore[no-untyped-def]
    http, _ = client
    loja = await _loja(http)
    r = await http.get(f"/lojas/{loja}/metricas")
    assert r.status_code == 200
    corpo = r.json()
    assert corpo["periodo"]["dias"] == 30
    assert corpo["periodo"]["fuso"] == "America/Sao_Paulo"
    assert len(corpo["series"]) == 30
    assert corpo["kpis"]["conversas_ativas"] == {"valor": 0.0, "anterior": 0.0, "variacao_pct": 0.0}
    assert corpo["kpis"]["latencia_llm_p95_ms"]["valor"] is None
    assert corpo["kpis"]["custo_total_usd"]["valor"] == "0.00"
    assert corpo["custo"]["completo"] is True
    assert corpo["ferramentas"] == [] and corpo["mapa_horario"] == []
    assert [e["etapa"] for e in corpo["funil"]][0] == "novo_contato"
    assert len(corpo["handoffs"]["por_motivo"]) == 4


async def test_periodo_informado_traz_numeros_e_comparacao(client) -> None:  # type: ignore[no-untyped-def]
    http, factory = client
    loja = await _loja(http)
    from uuid import UUID

    async with factory() as s:
        lead = Lead(loja_id=UUID(loja), telefone="1", canal="webchat", etapa="novo_contato")
        s.add(lead)
        await s.flush()
        conversa = Conversa(loja_id=UUID(loja), lead_id=lead.id, canal="webchat")
        s.add(conversa)
        await s.flush()
        s.add(
            Mensagem(
                loja_id=UUID(loja), conversa_id=conversa.id, canal="webchat", direcao="entrada",
                autor="cliente", conteudo="oi",
                criado_em=datetime(2026, 11, 10, 15, 0, tzinfo=UTC),
            )
        )  # fmt: skip
        payload: dict[str, Any] = {
            "modelo": "claude-sonnet-5-5", "entrada": 1_000_000, "saida": 0,
            "cache_leitura": 0, "cache_escrita": 0, "chamadas": 1,
            "tempo_resposta_ms": 2500,
        }  # fmt: skip
        s.add(
            Evento(
                loja_id=UUID(loja), lead_id=lead.id, tipo="llm_uso", payload=payload,
                criado_em=datetime(2026, 11, 10, 15, 1, tzinfo=UTC),
            )
        )  # fmt: skip
        await s.commit()

    r = await http.get(f"/lojas/{loja}/metricas", params={"de": "2026-11-08", "ate": "2026-11-14"})
    assert r.status_code == 200
    corpo = r.json()
    assert corpo["periodo"] == {
        "de": "2026-11-08", "ate": "2026-11-14", "dias": 7, "fuso": "America/Sao_Paulo",
        "anterior_de": "2026-11-01", "anterior_ate": "2026-11-07",
    }  # fmt: skip
    k = corpo["kpis"]
    assert k["conversas_ativas"]["valor"] == 1
    assert k["conversas_ativas"]["anterior"] == 0
    assert k["conversas_ativas"]["variacao_pct"] is None
    assert k["custo_total_usd"]["valor"] == "2.00"
    assert k["custo_por_conversa_usd"]["valor"] == "2.00"
    assert k["tempo_resposta_media_ms"]["valor"] == 2500
    assert corpo["custo"]["por_modelo"][0]["modelo"] == "claude-sonnet-5-5"
    ponto = next(p for p in corpo["series"] if p["dia"] == "2026-11-10")
    assert ponto["conversas_ativas"] == 1 and ponto["custo_usd"] == "2.00"
    assert corpo["mapa_horario"] == [{"dia_semana": 1, "hora": 12, "mensagens": 1}]


@pytest.mark.parametrize(
    "params",
    [
        {"de": "2026-11-10", "ate": "2026-11-09"},  # invertido
        {"de": "2024-01-01", "ate": "2026-11-09"},  # longo demais
        {"de": "ontem"},  # formato
    ],
)
async def test_periodo_invalido_e_422(client, params: dict[str, str]) -> None:  # type: ignore[no-untyped-def]
    http, _ = client
    loja = await _loja(http)
    r = await http.get(f"/lojas/{loja}/metricas", params=params)
    assert r.status_code == 422
    assert r.json()["erros"][0]["caminho"] == "de"


async def test_loja_inexistente_e_404(client) -> None:  # type: ignore[no-untyped-def]
    http, _ = client
    r = await http.get("/lojas/00000000-0000-0000-0000-000000000000/metricas")
    assert r.status_code == 404
    assert r.json()["erros"][0]["caminho"] == "loja_id"


async def test_hoje_aparece_no_ultimo_ponto_da_serie_padrao(client) -> None:  # type: ignore[no-untyped-def]
    http, _ = client
    loja = await _loja(http)
    corpo = (await http.get(f"/lojas/{loja}/metricas")).json()
    ultimo = date.fromisoformat(corpo["series"][-1]["dia"])
    assert abs((ultimo - datetime.now(UTC).date()).days) <= 1
    assert ultimo - timedelta(days=29) == date.fromisoformat(corpo["series"][0]["dia"])
