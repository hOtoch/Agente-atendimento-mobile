"""`scripts/custos.py --banco`: usage real dos eventos `llm_uso`, somado por conversa (lead)."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.adapters.outbound.db.models import Evento, Lead, Loja
from app.application.llm import UsoTokens
from tests.integration.conftest import aplicar_migrations
from tests.unit.scripts.carregar import carregar_custos

pytestmark = pytest.mark.integration

custos = carregar_custos()


def _uso(modelo: str, e: int, s: int, cl: int, ce: int, chamadas: int = 2) -> dict[str, object]:
    return {
        "modelo": modelo,
        "entrada": e,
        "saida": s,
        "cache_leitura": cl,
        "cache_escrita": ce,
        "chamadas": chamadas,
    }


async def test_soma_os_eventos_llm_uso_por_lead(db_url: str) -> None:
    await aplicar_migrations(db_url)
    engine = create_async_engine(db_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        loja = Loja(nome="Loja custos")
        s.add(loja)
        await s.flush()
        leads = [Lead(loja_id=loja.id, telefone=f"t{i}", canal="webchat") for i in range(2)]
        s.add_all(leads)
        await s.flush()
        a, b = leads[0].id, leads[1].id
        for lead, payload in [
            (a, _uso("claude-haiku-5-5", 100, 10, 1000, 50)),
            (a, _uso("claude-haiku-5-5", 200, 20, 2000, 0)),
            (b, _uso("claude-sonnet-5-5", 300, 30, 0, 0)),
        ]:
            s.add(Evento(loja_id=loja.id, lead_id=lead, tipo="llm_uso", payload=payload))
        s.add(Evento(loja_id=loja.id, lead_id=a, tipo="handoff", payload={"motivo": "x"}))
        s.add(Evento(loja_id=loja.id, lead_id=None, tipo="llm_uso", payload=_uso("x", 1, 1, 0, 0)))
        await s.commit()
    await engine.dispose()

    conversas = await custos.ler_usos_do_banco(db_url)
    por_modelos = sorted(conversas, key=lambda c: c[0].modelo)
    assert por_modelos == [
        [UsoTokens("claude-haiku-5-5", 300, 30, 3000, 50)],
        [UsoTokens("claude-sonnet-5-5", 300, 30, 0, 0)],
    ]
