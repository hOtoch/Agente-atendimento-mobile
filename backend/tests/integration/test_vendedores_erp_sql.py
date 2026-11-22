"""Vendedores do ERP no Postgres real: `codigo_erp`, criar/atualizar e importacao completa."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.outbound.db.conexao_erp import RepositorioConexaoErpSql
from app.adapters.outbound.db.config import RepositorioLojasSql, RepositorioVendedoresSql
from app.adapters.outbound.db.models import Lead, Vendedor
from app.application.config.entradas import EntradaVendedor
from app.application.config.vendedores_erp import ImportarVendedoresErp, VendedorErp
from app.domain.conexao_erp import ConexaoErp

pytestmark = pytest.mark.integration

D = Decimal


class LeitorFalso:
    def __init__(self) -> None:
        self.itens: list[VendedorErp] = []

    async def listar(self, system_unit_id: int) -> list[VendedorErp]:
        return list(self.itens)


async def _loja(session: AsyncSession) -> UUID:
    loja_id = await RepositorioLojasSql(session).criar("Loja V")
    await RepositorioConexaoErpSql(session).salvar(ConexaoErp(loja_id=loja_id, system_unit_id=12))
    await session.commit()
    return loja_id


async def test_criar_do_erp_entra_com_peso_zero_ativo_e_codigo(session: AsyncSession) -> None:
    loja_id = await _loja(session)
    repo = RepositorioVendedoresSql(session)

    criado = await repo.criar_do_erp(loja_id, "9", "Fulano")

    assert (criado.codigo_erp, criado.nome, criado.peso_percentual, criado.ativo) == (
        "9",
        "Fulano",
        D(0),
        True,
    )
    assert criado.telefone is None
    assert await repo.listar(loja_id) == [criado]
    assert await repo.pesos_ativos(loja_id) == [D(0)]


async def test_atualizar_do_erp_mexe_so_em_nome_e_ativo(session: AsyncSession) -> None:
    loja_id = await _loja(session)
    repo = RepositorioVendedoresSql(session)
    criado = await repo.criar_do_erp(loja_id, "9", "Fulano")
    await repo.substituir(
        loja_id,
        [
            EntradaVendedor(
                id=criado.id, nome="Fulano", telefone="+55 11 90000-0001", peso_percentual=D("100")
            )
        ],
    )

    await repo.atualizar_do_erp(loja_id, criado.id, nome="Fulano Silva", ativo=False)

    (v,) = await repo.listar(loja_id)
    assert (v.nome, v.ativo, v.codigo_erp) == ("Fulano Silva", False, "9")
    assert (v.telefone, v.peso_percentual) == ("+55 11 90000-0001", D("100"))


async def test_atualizar_de_outra_loja_nao_faz_nada(session: AsyncSession) -> None:
    loja_a = await _loja(session)
    loja_b = await _loja(session)
    repo = RepositorioVendedoresSql(session)
    criado = await repo.criar_do_erp(loja_a, "9", "Fulano")

    await repo.atualizar_do_erp(loja_b, criado.id, nome="Invasor", ativo=False)

    assert (await repo.listar(loja_a))[0].nome == "Fulano"


async def test_substituir_preserva_codigo_erp_ao_atualizar_e_ao_desativar(
    session: AsyncSession,
) -> None:
    loja_id = await _loja(session)
    repo = RepositorioVendedoresSql(session)
    criado = await repo.criar_do_erp(loja_id, "9", "Fulano")
    await repo.substituir(
        loja_id,
        [EntradaVendedor(id=criado.id, nome="Fulano", telefone=None, peso_percentual=D("100"))],
    )
    assert (await repo.listar(loja_id))[0].codigo_erp == "9"

    await repo.substituir(loja_id, [])  # ausente na lista = desativado
    (v,) = await repo.listar(loja_id)
    assert (v.ativo, v.codigo_erp) == (False, "9")


async def test_importacao_ponta_a_ponta_reimporta_sem_duplicar_e_preserva_leads(
    session: AsyncSession,
) -> None:
    loja_id = await _loja(session)
    repo = RepositorioVendedoresSql(session)
    leitor = LeitorFalso()
    caso = ImportarVendedoresErp(
        RepositorioLojasSql(session), RepositorioConexaoErpSql(session), repo, leitor
    )
    leitor.itens = [VendedorErp("1", "Ana", True), VendedorErp("2", "Bruno", True)]
    r1 = await caso.executar(loja_id)
    assert (r1.criados, r1.atualizados, r1.desativados) == (2, 0, 0)

    ana, bruno = await repo.listar(loja_id)
    await repo.substituir(
        loja_id,
        [
            EntradaVendedor(
                id=ana.id, nome="Ana", telefone="+55 11 90000-0001", peso_percentual=D("70")
            ),
            EntradaVendedor(id=bruno.id, nome="Bruno", telefone=None, peso_percentual=D("30")),
        ],
    )
    session.add(
        Lead(loja_id=loja_id, canal="webchat", telefone="5511999990000", vendedor_id=bruno.id)
    )
    await session.flush()

    leitor.itens = [VendedorErp("1", "Ana", True)]  # Bruno saiu do ERP
    r2 = await caso.executar(loja_id)
    r3 = await caso.executar(loja_id)

    assert (r2.criados, r2.atualizados, r2.desativados) == (0, 0, 1)
    assert (r3.criados, r3.atualizados, r3.desativados) == (0, 0, 0)
    por_codigo = {v.codigo_erp: v for v in await repo.listar(loja_id)}
    assert len(por_codigo) == 2
    assert por_codigo["1"].telefone == "+55 11 90000-0001"
    assert por_codigo["1"].peso_percentual == D("70")
    assert por_codigo["2"].ativo is False
    lead = (await session.execute(select(Lead))).scalar_one()
    assert lead.vendedor_id == bruno.id
    assert len((await session.execute(select(Vendedor))).scalars().all()) == 2
