"""Importador xlsx com Postgres: transacao unica e estoque importado ate o PlanilhaAdapter."""

from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.adapters.outbound.db.config import RepositorioEstoqueLocalSql
from app.adapters.outbound.estoque.banco import FonteEstoqueLocalSql
from app.adapters.outbound.estoque.planilha import PlanilhaAdapter
from app.adapters.outbound.planilhas.leitor import LeitorXlsx
from app.application.importacao.importar import ImportarPlanilha
from app.domain.estoque import Condicao
from app.infra.dependencias import montar_casos_config
from tests.unit.importacao.planilhas import estoque_xlsx, taxas_xlsx

pytestmark = pytest.mark.integration


async def _loja(session: AsyncSession) -> UUID:
    casos = montar_casos_config(session)
    loja = await casos.criar_loja("Loja Import")
    await session.commit()
    return loja


async def test_estoque_importado_chega_ao_planilha_adapter(session: AsyncSession) -> None:
    loja = await _loja(session)
    imp = ImportarPlanilha(montar_casos_config(session), LeitorXlsx(), commit=session.commit)
    planilha = estoque_xlsx(
        [
            ["A1", "iPhone 15 Pro", "256GB", "Titânio Natural", "novo", "R$ 7.500", 2, None],
            ["A2", "iPhone 15 Pro", 128, "Preto", "seminovo", "6.100,00", 1, "89%"],
            ["A3", "iPhone 13", 128, "Azul", "novo", 3000, 0, None],
            [None] * 8,
        ]
    )
    r = await imp.executar(loja, "estoque", planilha, "aplicar")
    assert r.ok, r.erros

    adapter = PlanilhaAdapter(FonteEstoqueLocalSql(RepositorioEstoqueLocalSql(session)))
    achados = await adapter.buscar(loja, "iphone 15 pro")
    assert sorted(i.sku for i in achados) == ["A1", "A2"]
    semi = next(i for i in achados if i.sku == "A2")
    assert semi.condicao is Condicao.SEMINOVO and semi.bateria_pct == 89
    assert str(semi.preco_pix.valor) == "6100.00"
    assert await adapter.buscar(loja, "iphone 13") == []  # esgotado
    assert (await adapter.obter(loja, "A3")) is not None


async def test_validar_nao_grava_no_banco(session: AsyncSession) -> None:
    loja = await _loja(session)
    imp = ImportarPlanilha(montar_casos_config(session), LeitorXlsx(), commit=session.commit)
    r = await imp.executar(
        loja,
        "estoque",
        estoque_xlsx([["A1", "iPhone 15", 128, "Preto", "novo", 1, 1, None]]),
        "validar",
    )
    assert r.ok
    assert await RepositorioEstoqueLocalSql(session).listar(loja) == []


async def test_aplicar_com_erro_nao_grava_nada(session: AsyncSession) -> None:
    loja = await _loja(session)
    imp = ImportarPlanilha(montar_casos_config(session), LeitorXlsx(), commit=session.commit)
    ruim = estoque_xlsx(
        [
            ["A1", "iPhone 15", 128, "Preto", "novo", 1, 1, None],
            ["A2", "iPhone 15", 128, "Preto", "quebrado", 1, 1, None],
        ]
    )
    r = await imp.executar(loja, "estoque", ruim, "aplicar")
    assert not r.ok and [e.caminho for e in r.erros] == ["estoque!E3"]
    assert await RepositorioEstoqueLocalSql(session).listar(loja) == []


async def test_taxas_sao_gravadas_numa_transacao(session: AsyncSession, db_url: str) -> None:
    """Se a 2a escrita (taxas) falha depois da 1a (regras de preco), o rollback desfaz as duas."""
    from sqlalchemy.ext.asyncio import create_async_engine

    loja = await _loja(session)
    casos = montar_casos_config(session)

    async def quebra(*_: object) -> None:
        raise RuntimeError("falha no meio")

    original = casos.atualizar_taxas
    casos.atualizar_taxas = quebra  # type: ignore[method-assign]
    imp = ImportarPlanilha(casos, LeitorXlsx(), commit=session.commit, rollback=session.rollback)
    planilha = taxas_xlsx([[1, 1.99, None, None, None, None]])
    with pytest.raises(RuntimeError):
        await imp.executar(loja, "taxas", planilha, "aplicar")

    engine = create_async_engine(db_url)
    try:
        async with async_sessionmaker(engine)() as outra:
            assert await montar_casos_config(outra).obter_preco(loja) is None
    finally:
        await engine.dispose()

    # sem falha, as duas gravacoes aparecem juntas
    casos.atualizar_taxas = original  # type: ignore[method-assign]
    r = await imp.executar(loja, "taxas", planilha, "aplicar")
    assert r.ok, r.erros
    assert (await montar_casos_config(session).obter_preco(loja)) is not None
    assert len((await montar_casos_config(session).obter_taxas(loja)).taxas) == 1
