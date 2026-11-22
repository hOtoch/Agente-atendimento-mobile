"""Sincronizacao do estoque com o Mercado Phone sobre Postgres real e servidor MCP falso.

Fecha o caminho: ERP falso -> mapeamento -> `estoque_local` -> `consultar_estoque` do agente.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.adapters.outbound.db.conexao_erp import RepositorioConexaoErpSql
from app.adapters.outbound.db.config import RepositorioEstoqueLocalSql, RepositorioLojasSql
from app.adapters.outbound.db.models import EstoqueLocalRow
from app.adapters.outbound.estoque.banco import FonteEstoqueLocalSql
from app.adapters.outbound.estoque.planilha import PlanilhaAdapter
from app.adapters.outbound.mercadophone.cliente import ClienteMercadoPhone
from app.adapters.outbound.mercadophone.fonte import FonteEstoqueMercadoPhone
from app.application.agente.contexto import ContextoFerramentas
from app.application.agente.estado import EstadoAtendimento
from app.application.agente.ferramentas import CatalogoFerramentas
from app.application.estoque_erp import SincronizarEstoqueErp
from app.application.estoque_resiliente import EstoqueResiliente
from app.application.relogio import RelogioFalso
from app.domain.conexao_erp import ConexaoErp
from app.infra.composicao import (
    criar_sincronizador_erp,
    montar_casos_config,
    montar_sincronizar_estoque_erp,
)
from app.infra.fila import RelogioParede
from tests.mercadophone_falso import CHAVE, URL, McpFalso, item

pytestmark = pytest.mark.integration

AGORA = datetime(2026, 11, 22, 12, 0, tzinfo=UTC)


def _fonte(mcp: McpFalso) -> FonteEstoqueMercadoPhone:
    return FonteEstoqueMercadoPhone(
        ClienteMercadoPhone(mcp.cliente_http(), URL, CHAVE, relogio=RelogioFalso())
    )


async def _loja_com_conexao(session: AsyncSession, **campos: Any) -> UUID:
    loja_id = await RepositorioLojasSql(session).criar("Loja")
    base: dict[str, Any] = {"system_unit_id": 4, "ativo": True}
    await RepositorioConexaoErpSql(session).salvar(
        ConexaoErp(loja_id=loja_id, **{**base, **campos})
    )
    await session.commit()
    return loja_id


def _caso(session: AsyncSession, mcp: McpFalso, agora: datetime = AGORA) -> SincronizarEstoqueErp:
    return montar_sincronizar_estoque_erp(session, _fonte(mcp), agora=lambda: agora)


async def _skus(session: AsyncSession, loja_id: UUID) -> list[str]:
    linhas = await RepositorioEstoqueLocalSql(session).listar(loja_id)
    return [linha.sku for linha in linhas]


async def _conexao(session: AsyncSession, loja_id: UUID) -> ConexaoErp:
    c = await RepositorioConexaoErpSql(session).obter(loja_id)
    assert c is not None
    return c


async def test_sincroniza_grava_o_estoque_com_o_id_do_erp_e_o_agente_encontra_o_item(
    session: AsyncSession,
) -> None:
    loja_id = await _loja_com_conexao(session)
    mcp = McpFalso({4: [item(11, sku="IP15P-256-PRETO", preco=4200), item(12, modelo="IPHONE 13")]})

    resultado = await _caso(session, mcp).sincronizar(await _conexao(session, loja_id))

    assert resultado.status == "ok"
    linhas = await RepositorioEstoqueLocalSql(session).listar(loja_id)
    assert {(x.sku, x.erp_produto_id) for x in linhas} == {
        ("IP15P-256-PRETO", 11),
        ("TESTE-00012", 12),
    }
    # caminho real do agente: banco -> planilha -> resiliente -> ferramenta consultar_estoque
    estoque = EstoqueResiliente(
        PlanilhaAdapter(FonteEstoqueLocalSql(RepositorioEstoqueLocalSql(session))), RelogioParede()
    )
    ctx = ContextoFerramentas(
        loja_id=loja_id,
        lead_id=uuid4(),
        estoque=estoque,
        config=montar_casos_config(session),
        hoje=AGORA.date(),
    )
    r = await CatalogoFerramentas().executar(
        "consultar_estoque",
        {"modelo": "iPhone 15 Pro", "capacidade": "256GB"},
        EstadoAtendimento(),
        ctx,
    )
    assert r.erro is False
    assert r.conteudo["total_opcoes"] == 1
    assert r.conteudo["opcoes"][0]["sku"] == "IP15P-256-PRETO"
    assert r.estado.ficha.interesse.sku_estoque_confirmado == "IP15P-256-PRETO"


async def test_falha_na_pagina_n_nao_apaga_nem_altera_o_estoque(session: AsyncSession) -> None:
    loja_id = await _loja_com_conexao(session)
    bom = McpFalso({4: [item(i) for i in range(1, 651)]})
    await _caso(session, bom).sincronizar(await _conexao(session, loja_id))
    antes = await RepositorioEstoqueLocalSql(session).listar(loja_id)
    assert len(antes) == 650

    quebrado = McpFalso(
        {4: [item(i, preco=1.5) for i in range(1, 701)]},
        falha_na_pagina={3: httpx.Response(503)},
    )
    resultado = await _caso(session, quebrado, AGORA + timedelta(minutes=15)).sincronizar(
        await _conexao(session, loja_id)
    )

    assert resultado.status == "erro"
    session.expire_all()
    assert await RepositorioEstoqueLocalSql(session).listar(loja_id) == antes
    c = await _conexao(session, loja_id)
    assert c.ultimo_status == "erro"
    assert c.ultima_sincronizacao_em == AGORA + timedelta(minutes=15)
    assert c.ultimo_relatorio is not None
    assert c.ultimo_relatorio["retentavel"] is True


async def test_rodar_duas_vezes_da_o_mesmo_estoque(session: AsyncSession) -> None:
    loja_id = await _loja_com_conexao(session)
    mcp = McpFalso({4: [item(i) for i in range(1, 21)]})
    await _caso(session, mcp).sincronizar(await _conexao(session, loja_id))
    primeiro = await RepositorioEstoqueLocalSql(session).listar(loja_id)
    await _caso(session, mcp).sincronizar(await _conexao(session, loja_id))
    assert await RepositorioEstoqueLocalSql(session).listar(loja_id) == primeiro
    ids = (
        await session.execute(select(EstoqueLocalRow.id).where(EstoqueLocalRow.loja_id == loja_id))
    ).all()
    assert len(ids) == 20


async def test_item_removido_do_erp_sai_do_estoque_local(session: AsyncSession) -> None:
    loja_id = await _loja_com_conexao(session)
    await _caso(session, McpFalso({4: [item(1), item(2)]})).sincronizar(
        await _conexao(session, loja_id)
    )
    await _caso(session, McpFalso({4: [item(2)]})).sincronizar(await _conexao(session, loja_id))
    assert await _skus(session, loja_id) == ["TESTE-00002"]


async def test_sku_duplicado_no_erp_nao_quebra_a_constraint(session: AsyncSession) -> None:
    loja_id = await _loja_com_conexao(session)
    mcp = McpFalso({4: [item(1, sku="DUP", preco=100), item(2, sku="DUP", preco=999)]})
    resultado = await _caso(session, mcp).sincronizar(await _conexao(session, loja_id))
    assert resultado.status == "ok"
    (unica,) = await RepositorioEstoqueLocalSql(session).listar(loja_id)
    assert (unica.sku, unica.erp_produto_id, str(unica.preco_pix.valor)) == ("DUP", 1, "100.00")
    assert resultado.relatorio["por_motivo"] == {"sku_duplicado": 1}


async def test_cron_duas_lojas_na_mesma_unidade_leem_uma_vez_e_filtram(
    session: AsyncSession,
) -> None:
    loja_a = await _loja_com_conexao(session, filtro_loja="Loja A")
    loja_b = await _loja_com_conexao(session, filtro_loja="Loja B")
    inativa = await _loja_com_conexao(session, ativo=False)
    itens = [item(1, obs="Loja A"), item(2, obs="Loja A | vitrine"), item(3, obs="Loja B")]
    mcp = McpFalso({4: itens})

    resultados = await _caso(session, mcp).sincronizar_vencidas()

    assert mcp.leituras_do_inventario() == 1
    assert [r.status for r in resultados] == ["ok", "ok"]
    assert sorted(await _skus(session, loja_a)) == ["TESTE-00001", "TESTE-00002"]
    assert await _skus(session, loja_b) == ["TESTE-00003"]
    assert await _skus(session, inativa) == []
    assert (await _conexao(session, inativa)).ultimo_status is None


@pytest.fixture
async def factory(db_url: str) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    from tests.integration.conftest import aplicar_migrations

    await aplicar_migrations(db_url)
    engine = create_async_engine(db_url)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def test_hook_do_cron_abre_sessao_propria_e_devolve_quantas_lojas_sincronizou(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    async with factory() as s:
        loja_id = await _loja_com_conexao(s)
    mcp = McpFalso({4: [item(1), item(2)]})

    sincronizar = criar_sincronizador_erp(factory, fonte=_fonte(mcp), agora=lambda: AGORA)
    assert await sincronizar() == 1
    assert await sincronizar() == 0  # ainda nao venceu

    async with factory() as s:
        assert len(await _skus(s, loja_id)) == 2
        assert (await _conexao(s, loja_id)).ultimo_status == "ok"
