"""Repositorios SQLAlchemy da configuracao da loja: ida e volta sem perda + migration 0002."""

from decimal import Decimal
from uuid import UUID

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import inspect, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.adapters.outbound.db.config import (
    LeitorVendedoresSql,
    RepositorioConfigLojaSql,
    RepositorioEstoqueLocalSql,
    RepositorioLojasSql,
    RepositorioMapeamentoSkuSql,
)
from app.adapters.outbound.db.models import Base, Vendedor
from app.application.config.modelos import (
    ConfigPreco,
    LinhaEstoqueLocal,
    LinhaMapeamentoSku,
    PerfilLoja,
)
from app.domain.bandeira import Bandeira
from app.domain.desconto import PoliticaDesconto, RegraOportunidadeUnica
from app.domain.pagamento import DescontoPixNenhum, DescontoPixValor, RegrasPreco, TabelaTaxas
from app.domain.troca import SEM, LinhaTroca, TabelaTroca
from app.domain.valores import Capacidade, Dinheiro, ModeloAparelho
from tests.integration.conftest import aplicar_migrations

pytestmark = pytest.mark.integration

D = Decimal
NOVAS = {
    "perfil_loja",
    "regras_preco",
    "taxas",
    "tabela_troca",
    "estoque_local",
    "mapeamento_sku",
}


async def _loja(session: AsyncSession) -> UUID:
    loja_id = await RepositorioLojasSql(session).criar("Loja X")
    await session.commit()
    return loja_id


async def test_migration_0002_sobe_e_desce(db_url: str) -> None:
    engine = create_async_engine(db_url)
    try:
        await aplicar_migrations(db_url, "0001")
        async with engine.connect() as conn:
            antes = await conn.run_sync(lambda c: set(inspect(c).get_table_names()))
        assert not NOVAS & antes

        await aplicar_migrations(db_url, "head")
        async with engine.connect() as conn:
            depois = await conn.run_sync(lambda c: set(inspect(c).get_table_names()))
            diffs = await conn.run_sync(
                lambda c: compare_metadata(MigrationContext.configure(c), Base.metadata)
            )
        assert depois >= NOVAS
        assert diffs == []

        await aplicar_migrations(db_url, "base")
        async with engine.connect() as conn:
            fim = await conn.run_sync(lambda c: set(inspect(c).get_table_names()))
        assert fim == {"alembic_version"} or fim == set()
    finally:
        await engine.dispose()


async def test_loja_existe(session: AsyncSession) -> None:
    repo = RepositorioLojasSql(session)
    loja = await _loja(session)
    assert await repo.existe(loja)
    assert not await repo.existe(UUID(int=1))


async def test_perfil_ida_e_volta_e_upsert(session: AsyncSession) -> None:
    loja = await _loja(session)
    repo = RepositorioConfigLojaSql(session)
    assert await repo.obter_perfil(loja) is None
    perfil = PerfilLoja(
        "Loja", "Direto", "Rua A", {"seg-sex": "9-18", "sab": "9-13"}, "5511999990000"
    )
    await repo.salvar_perfil(loja, perfil)
    assert await repo.obter_perfil(loja) == perfil
    novo = PerfilLoja("Loja 2", "", "", {}, "")
    await repo.salvar_perfil(loja, novo)
    session.expire_all()
    assert await repo.obter_perfil(loja) == novo


async def test_config_preco_ida_e_volta(session: AsyncSession) -> None:
    loja = await _loja(session)
    repo = RepositorioConfigLojaSql(session)
    assert await repo.obter_config_preco(loja) is None
    config = ConfigPreco(
        RegrasPreco(18, True, DescontoPixValor(Dinheiro.de("80")), True),
        PoliticaDesconto(Dinheiro.de("120"), Dinheiro.de("50")),
        RegraOportunidadeUnica(True, 14, Dinheiro.de("100"), True),
    )
    await repo.salvar_config_preco(loja, config)
    assert await repo.obter_config_preco(loja) == config

    outra = ConfigPreco(
        RegrasPreco(3, False, DescontoPixNenhum(), False),
        PoliticaDesconto(Dinheiro.de("0"), Dinheiro.de("10")),
        RegraOportunidadeUnica(False, 0, Dinheiro.zero(), False),
    )
    await repo.salvar_config_preco(loja, outra)
    session.expire_all()
    assert await repo.obter_config_preco(loja) == outra


async def test_taxas_ida_e_volta_preserva_igual_none(session: AsyncSession) -> None:
    loja = await _loja(session)
    repo = RepositorioConfigLojaSql(session)
    assert (await repo.obter_taxas(loja)).taxas == {}
    tabela = TabelaTaxas(
        {
            (12, Bandeira.MASTERCARD): D("10.54"),
            (12, Bandeira.VISA): None,
            ("debito", Bandeira.ELO): D("1.5"),
            (1, Bandeira.AMEX): D("0"),
        }
    )
    await repo.salvar_taxas(loja, tabela)
    session.expire_all()
    lida = await repo.obter_taxas(loja)
    assert lida.taxas == tabela.taxas
    assert lida.taxas[(12, Bandeira.VISA)] is None
    assert lida.taxas[(1, Bandeira.AMEX)] == 0

    await repo.salvar_taxas(loja, TabelaTaxas({(2, Bandeira.VISA): D("3")}))
    session.expire_all()
    assert (await repo.obter_taxas(loja)).taxas == {(2, Bandeira.VISA): D("3")}


def _linha(nome: str, cap: int, marca: str = "Apple", **sobre: object) -> LinhaTroca:
    campos: dict[str, object] = {
        "valor_sem_detalhes": Dinheiro.de("3100"),
        "desconto_tela": Dinheiro.de("600"),
        "desconto_traseira": Dinheiro.zero(),
        "desconto_carcaca": SEM,
        "desconto_bateria": Dinheiro.de("190.50"),
        "limite_bateria_pct": 80,
    }
    campos.update(sobre)
    return LinhaTroca(
        modelo=ModeloAparelho.de(nome, marca),
        capacidade=Capacidade(cap),
        **campos,  # type: ignore[arg-type]
    )


async def test_tabela_troca_ida_e_volta_preserva_sem_e_zero(session: AsyncSession) -> None:
    loja = await _loja(session)
    repo = RepositorioConfigLojaSql(session)
    tabela = TabelaTroca(
        linhas_apple=(
            _linha("iPhone 16", 128),
            _linha("iPhone 15", 256, desconto_tela=SEM, desconto_bateria=SEM),
            _linha("iPhone 15", 128),
        ),
        linhas_outras_marcas=(_linha("Galaxy S23", 256, marca="Samsung"),),
    )
    await repo.salvar_tabela_troca(loja, tabela)
    session.expire_all()
    lida = await repo.obter_tabela_troca(loja)
    assert lida == tabela  # ordem, SEM, zero e centavos preservados
    primeira, segunda, _ = lida.linhas_apple
    assert primeira.desconto_traseira == Dinheiro.zero()
    assert primeira.desconto_carcaca is SEM
    assert segunda.desconto_tela is SEM

    await repo.salvar_tabela_troca(loja, TabelaTroca())
    session.expire_all()
    assert await repo.obter_tabela_troca(loja) == TabelaTroca()


async def test_estoque_local_ida_e_volta(session: AsyncSession) -> None:
    loja = await _loja(session)
    repo = RepositorioEstoqueLocalSql(session)
    assert await repo.listar(loja) == []
    linhas = [
        LinhaEstoqueLocal(
            "B",
            ModeloAparelho.de("iPhone 16"),
            Capacidade(128),
            "Preto",
            "novo",
            Dinheiro.de("4500.90"),
            3,
            None,
        ),
        LinhaEstoqueLocal(
            "A",
            ModeloAparelho.de("iPhone 13"),
            Capacidade(256),
            "Azul",
            "seminovo",
            Dinheiro.de("2800"),
            1,
            88,
        ),
    ]
    await repo.substituir(loja, linhas)
    session.expire_all()
    assert await repo.listar(loja) == linhas

    await repo.substituir(loja, linhas[:1])
    session.expire_all()
    assert await repo.listar(loja) == linhas[:1]


async def test_mapeamento_sku_ida_e_volta(session: AsyncSession) -> None:
    loja = await _loja(session)
    repo = RepositorioMapeamentoSkuSql(session)
    linhas = [
        LinhaMapeamentoSku(
            "ERP-1", ModeloAparelho.de("iPhone 16 Pro"), Capacidade(256), "Titanio", "novo"
        ),
        LinhaMapeamentoSku(
            "ERP-2",
            ModeloAparelho.de("Galaxy S23", "Samsung"),
            Capacidade(128),
            "Preto",
            "seminovo",
        ),
    ]
    await repo.substituir(loja, linhas)
    session.expire_all()
    assert await repo.listar(loja) == linhas


async def test_isolamento_entre_lojas(session: AsyncSession) -> None:
    a = await _loja(session)
    b = await _loja(session)
    repo = RepositorioEstoqueLocalSql(session)
    linha = LinhaEstoqueLocal(
        "S",
        ModeloAparelho.de("iPhone 16"),
        Capacidade(128),
        "Preto",
        "novo",
        Dinheiro.de("1"),
        1,
        None,
    )
    await repo.substituir(a, [linha])
    await repo.substituir(b, [linha])
    await repo.substituir(a, [])
    assert await repo.listar(a) == []
    assert await repo.listar(b) == [linha]


async def test_leitor_vendedores_so_ativos(session: AsyncSession) -> None:
    loja = await _loja(session)
    session.add_all(
        [
            Vendedor(loja_id=loja, nome="A", peso_percentual=D("60")),
            Vendedor(loja_id=loja, nome="B", peso_percentual=D("40")),
            Vendedor(loja_id=loja, nome="C", peso_percentual=D("25"), ativo=False),
        ]
    )
    await session.flush()
    pesos = await LeitorVendedoresSql(session).pesos_ativos(loja)
    assert sorted(pesos) == [D("40"), D("60")]
    assert (await session.execute(select(Vendedor))).scalars().all()
