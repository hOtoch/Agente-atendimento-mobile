"""Seed da loja demo contra Postgres: idempotencia, exemplos oficiais e checklist completo."""

from decimal import Decimal

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.outbound.db.config import (
    LeitorVendedoresSql,
    RepositorioConfigLojaSql,
    RepositorioEstoqueLocalSql,
    RepositorioLojasSql,
    RepositorioMapeamentoSkuSql,
    RepositorioVendedoresSql,
)
from app.adapters.outbound.db.models import EstoqueLocalRow, Loja, TaxaRow, TrocaRow, Vendedor
from app.application.config.casos_de_uso import CasosDeUsoConfig
from app.application.config.portas import SemIntegracaoEstoque
from app.domain.bandeira import Bandeira
from app.domain.pagamento import Credito, calcular_pagamento
from app.domain.troca import CondicaoUsado, ValorTroca, avaliar_troca
from app.domain.valores import Capacidade, Dinheiro, ModeloAparelho
from app.infra.seed import LOJA_DEMO_ID, semear

pytestmark = pytest.mark.integration

TABELAS = (Loja, Vendedor, TaxaRow, TrocaRow, EstoqueLocalRow)


def _casos(session: AsyncSession) -> CasosDeUsoConfig:
    return CasosDeUsoConfig(
        lojas=RepositorioLojasSql(session),
        config=RepositorioConfigLojaSql(session),
        estoque=RepositorioEstoqueLocalSql(session),
        mapeamento=RepositorioMapeamentoSkuSql(session),
        vendedores=RepositorioVendedoresSql(session),
        integracao=SemIntegracaoEstoque(),
    )


async def _contagens(session: AsyncSession) -> dict[str, int]:
    session.expire_all()
    return {
        m.__tablename__: (await session.execute(select(func.count()).select_from(m))).scalar_one()
        for m in TABELAS
    }


async def test_rodar_duas_vezes_nao_duplica(db_url: str, session: AsyncSession) -> None:
    await semear(db_url)
    antes = await _contagens(session)
    await semear(db_url)
    depois = await _contagens(session)
    assert antes == depois
    assert antes["lojas"] == 1
    assert antes["vendedores"] == 3
    assert antes["taxas"] == 5 * 19
    assert antes["estoque_local"] >= 20


async def test_segunda_rodada_atualiza_valores(db_url: str, session: AsyncSession) -> None:
    await semear(db_url)
    await session.execute(update(EstoqueLocalRow).values(preco_pix=Decimal(1)))
    await session.execute(update(Vendedor).values(peso_percentual=Decimal(0)))
    await session.execute(update(Loja).values(nome="Alterada"))
    await session.commit()
    await semear(db_url)
    session.expire_all()
    estoque = await _casos(session).obter_estoque(LOJA_DEMO_ID)
    assert all(e.preco_pix > Dinheiro.de(1) for e in estoque)
    pesos = await LeitorVendedoresSql(session).pesos_ativos(LOJA_DEMO_ID)
    assert sorted(pesos) == [Decimal(20), Decimal(30), Decimal(50)]
    loja = await session.get(Loja, LOJA_DEMO_ID, populate_existing=True)
    assert loja is not None
    assert loja.nome == "Loja Demo Celulares"


async def test_exemplo_oficial_da_troca(db_url: str, session: AsyncSession) -> None:
    await semear(db_url)
    tabela = await _casos(session).obter_troca(LOJA_DEMO_ID)
    resultado = avaliar_troca(
        tabela,
        ModeloAparelho.de("iPhone 16"),
        Capacidade(128),
        CondicaoUsado(
            tela_danificada=True,
            traseira_danificada=False,
            carcaca_marcada=False,
            bateria_pct=79,
            camera_ok=True,
            outros_defeitos=(),
            peca_trocada=False,
        ),
    )
    assert isinstance(resultado, ValorTroca)
    assert resultado.valor == Dinheiro.de(2310)


async def test_exemplo_oficial_da_parcela(db_url: str, session: AsyncSession) -> None:
    await semear(db_url)
    casos = _casos(session)
    preco = await casos.obter_preco(LOJA_DEMO_ID)
    assert preco is not None
    taxas = await casos.obter_taxas(LOJA_DEMO_ID)
    proposta = calcular_pagamento(
        Dinheiro.de(4830),
        Dinheiro.zero(),
        Dinheiro.zero(),
        Credito(12, Bandeira.MASTERCARD),
        preco.regras,
        taxas,
    )
    assert proposta.valor_parcela == Dinheiro.de("444.92")


async def test_checklist_da_loja_demo_100_por_cento(db_url: str, session: AsyncSession) -> None:
    await semear(db_url)
    itens = await _casos(session).checklist(LOJA_DEMO_ID)
    assert itens
    assert all(i.completo for i in itens), [i for i in itens if not i.completo]


async def test_estoque_vale_mais_que_troca_no_banco(db_url: str, session: AsyncSession) -> None:
    await semear(db_url)
    casos = _casos(session)
    tabela = await casos.obter_troca(LOJA_DEMO_ID)
    for e in await casos.obter_estoque(LOJA_DEMO_ID):
        linha = tabela.buscar(e.modelo, e.capacidade)
        if linha is not None and linha.capacidade == e.capacidade:
            assert e.preco_pix > linha.valor_sem_detalhes, e.sku
