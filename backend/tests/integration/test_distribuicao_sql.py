"""Distribuicao de leads em Postgres: contagem, gravacao e trava por loja sob concorrencia."""

from __future__ import annotations

import asyncio
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.adapters.outbound.db.config import RepositorioVendedoresSql
from app.adapters.outbound.db.distribuicao import AtribuicoesLeadSql
from app.adapters.outbound.db.models import Lead, Loja, Vendedor
from app.application.config.entradas import EntradaVendedor
from app.application.distribuir_lead import LeadNaoEncontrado
from app.domain.distribuicao import SemVendedorDisponivel
from app.infra.composicao import montar_distribuir_lead

pytestmark = pytest.mark.integration

D = Decimal


async def _loja_com_vendedores(session: AsyncSession, *pesos: str) -> tuple[UUID, list[UUID]]:
    loja = Loja(nome="L")
    session.add(loja)
    await session.flush()
    vendedores = await RepositorioVendedoresSql(session).substituir(
        loja.id,
        [
            EntradaVendedor(id=None, nome=f"V{i}", telefone=None, peso_percentual=D(p), ativo=True)
            for i, p in enumerate(pesos)
        ],
    )
    await session.commit()
    return loja.id, [v.id for v in vendedores]


async def _novos_leads(
    session: AsyncSession, loja_id: UUID, n: int, prefixo: str = ""
) -> list[UUID]:
    leads = [Lead(loja_id=loja_id, telefone=f"{prefixo}{i}", canal="webchat") for i in range(n)]
    session.add_all(leads)
    await session.commit()
    return [lead.id for lead in leads]


async def _contagem(session: AsyncSession, loja_id: UUID) -> dict[UUID, int]:
    rows = await session.execute(
        select(Lead.vendedor_id, func.count())
        .where(Lead.loja_id == loja_id, Lead.vendedor_id.is_not(None))
        .group_by(Lead.vendedor_id)
    )
    return {v: n for v, n in rows}


async def test_distribui_e_grava_vendedor_no_lead(session: AsyncSession) -> None:
    loja, (a, b) = await _loja_com_vendedores(session, "70", "30")
    leads = await _novos_leads(session, loja, 100)
    caso = montar_distribuir_lead(session)
    for lead in leads:
        r = await caso.executar(loja, lead)
        assert isinstance(r, UUID)
    await session.commit()
    assert await _contagem(session, loja) == {a: 70, b: 30}


async def test_nao_mexe_no_dono(session: AsyncSession) -> None:
    loja, _ = await _loja_com_vendedores(session, "100")
    (lead,) = await _novos_leads(session, loja, 1)
    await montar_distribuir_lead(session).executar(loja, lead)
    await session.commit()
    row = (await session.execute(select(Lead).where(Lead.id == lead))).scalar_one()
    assert row.dono == "ia"
    assert row.vendedor_id is not None


async def test_inativo_nao_recebe(session: AsyncSession) -> None:
    loja, (a, b) = await _loja_com_vendedores(session, "50", "50")
    (await session.get(Vendedor, b)).ativo = False  # type: ignore[union-attr]
    await session.commit()
    leads = await _novos_leads(session, loja, 10)
    caso = montar_distribuir_lead(session)
    for lead in leads:
        assert await caso.executar(loja, lead) == a
    await session.commit()
    assert await _contagem(session, loja) == {a: 10}


async def test_sem_vendedor_disponivel(session: AsyncSession) -> None:
    loja, _ = await _loja_com_vendedores(session)
    (lead,) = await _novos_leads(session, loja, 1)
    r = await montar_distribuir_lead(session).executar(loja, lead)
    assert isinstance(r, SemVendedorDisponivel)


async def test_idempotente(session: AsyncSession) -> None:
    loja, _ = await _loja_com_vendedores(session, "50", "50")
    (lead,) = await _novos_leads(session, loja, 1)
    caso = montar_distribuir_lead(session)
    primeiro = await caso.executar(loja, lead)
    assert await caso.executar(loja, lead) == primeiro
    await session.commit()
    assert sum((await _contagem(session, loja)).values()) == 1


async def test_lead_de_outra_loja_ou_inexistente(session: AsyncSession) -> None:
    loja, _ = await _loja_com_vendedores(session, "100")
    outra, _ = await _loja_com_vendedores(session, "100")
    (lead_outra,) = await _novos_leads(session, outra, 1)
    caso = montar_distribuir_lead(session)
    with pytest.raises(LeadNaoEncontrado):
        await caso.executar(loja, lead_outra)
    with pytest.raises(LeadNaoEncontrado):
        await caso.executar(loja, UUID(int=1))


async def test_contagem_so_da_propria_loja(session: AsyncSession) -> None:
    loja, (a,) = await _loja_com_vendedores(session, "100")
    outra, (b,) = await _loja_com_vendedores(session, "100")
    for lead in await _novos_leads(session, outra, 5):
        await montar_distribuir_lead(session).executar(outra, lead)
    await session.commit()
    repo = AtribuicoesLeadSql(session)
    assert await repo.contar_por_vendedor(loja) == {}
    assert await repo.contar_por_vendedor(outra) == {b: 5}
    assert a != b


async def test_concorrencia_na_mesma_loja_respeita_a_proporcao(
    session: AsyncSession, db_url: str
) -> None:
    loja, (a, b) = await _loja_com_vendedores(session, "50", "50")
    leads = await _novos_leads(session, loja, 40)

    engine = create_async_engine(db_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def distribuir(lead: UUID) -> None:
        async with factory() as s:
            await montar_distribuir_lead(s).executar(loja, lead)
            await s.commit()

    try:
        await asyncio.gather(*(distribuir(lead) for lead in leads))
    finally:
        await engine.dispose()

    # com a trava por loja, as 40 distribuicoes concorrentes se serializam: exatamente 20/20
    assert await _contagem(session, loja) == {a: 20, b: 20}


async def test_trava_de_lojas_diferentes_nao_se_bloqueia(
    session: AsyncSession, db_url: str
) -> None:
    loja1, _ = await _loja_com_vendedores(session, "100")
    loja2, _ = await _loja_com_vendedores(session, "100")
    (lead1,) = await _novos_leads(session, loja1, 1)
    (lead2,) = await _novos_leads(session, loja2, 1)

    engine = create_async_engine(db_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as s1, factory() as s2:
            # s1 segura a trava da loja1 sem commitar; s2 (loja2) nao pode esperar por ela
            await montar_distribuir_lead(s1).executar(loja1, lead1)
            await asyncio.wait_for(montar_distribuir_lead(s2).executar(loja2, lead2), timeout=5)
            await s2.commit()
            await s1.commit()
    finally:
        await engine.dispose()
