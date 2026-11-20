"""RepositorioAtendimentoSql contra Postgres real (tabela `fichas`, versionada)."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.outbound.db.atendimento import RepositorioAtendimentoSql
from app.adapters.outbound.db.config import RepositorioLojasSql
from app.adapters.outbound.db.conversas import RepositorioConversasSql
from app.adapters.outbound.db.models import Ficha as FichaRow
from app.application.agente.estado import EstadoAtendimento
from app.application.canal import Canal
from app.domain.desconto import EstadoDesconto
from app.domain.ficha import Ficha, TipoPagamento
from app.domain.valores import Bandeira, Capacidade, Dinheiro, ModeloAparelho

pytestmark = pytest.mark.integration


async def _loja_e_lead(session: AsyncSession, contato: str = "sessao-1") -> tuple[UUID, UUID]:
    loja_id = await RepositorioLojasSql(session).criar("Loja")
    await session.commit()
    lead_id, _ = await RepositorioConversasSql(session).obter_ou_criar(
        loja_id, Canal.WEBCHAT, contato
    )
    return loja_id, lead_id


def _estado() -> EstadoAtendimento:
    ficha = (
        Ficha.vazia()
        .com_interesse(
            modelo=ModeloAparelho.de("iPhone 16"),
            capacidade=Capacidade(128),
            sku_estoque_confirmado="SKU-1",
        )
        .com(tem_troca=False, data_prevista_compra=date(2026, 12, 1))
        .com_pagamento(tipo=TipoPagamento.CREDITO, parcelas=12, bandeira=Bandeira.MASTERCARD)
    )
    return EstadoAtendimento(
        ficha=ficha,
        desconto=EstadoDesconto(Dinheiro(Decimal("50.00"))),
        estoque_consultado=True,
        proposta_apresentada=True,
        ultima_proposta={"preco_aparelho": "R$ 4.830,00"},
    )


async def test_obter_sem_registro_devolve_vazio(session: AsyncSession) -> None:
    loja_id, lead_id = await _loja_e_lead(session)
    assert await RepositorioAtendimentoSql(session).obter(loja_id, lead_id) == EstadoAtendimento()


async def test_ida_e_volta_sem_perda(session: AsyncSession) -> None:
    loja_id, lead_id = await _loja_e_lead(session)
    repo = RepositorioAtendimentoSql(session)
    await repo.salvar(loja_id, lead_id, _estado())
    assert await repo.obter(loja_id, lead_id) == _estado()


async def test_versoes_crescentes_e_obter_le_a_maior(session: AsyncSession) -> None:
    loja_id, lead_id = await _loja_e_lead(session)
    repo = RepositorioAtendimentoSql(session)
    e1 = _estado()
    e2 = replace(e1, handoff_solicitado=True, motivo_handoff="quer fechar")
    assert await repo.salvar(loja_id, lead_id, e1) == 1
    assert await repo.salvar(loja_id, lead_id, e2) == 2
    assert await repo.salvar(loja_id, lead_id, e2) == 3
    assert await repo.obter(loja_id, lead_id) == e2
    versoes = (
        (await session.execute(select(FichaRow.versao).where(FichaRow.lead_id == lead_id)))
        .scalars()
        .all()
    )
    assert sorted(versoes) == [1, 2, 3]


async def test_leads_tem_versoes_independentes(session: AsyncSession) -> None:
    loja_id, lead_a = await _loja_e_lead(session, "a")
    lead_b, _ = await RepositorioConversasSql(session).obter_ou_criar(loja_id, Canal.WEBCHAT, "b")
    repo = RepositorioAtendimentoSql(session)
    await repo.salvar(loja_id, lead_a, _estado())
    await repo.salvar(loja_id, lead_a, _estado())
    assert await repo.salvar(loja_id, lead_b, EstadoAtendimento()) == 1
    assert await repo.obter(loja_id, lead_b) == EstadoAtendimento()
