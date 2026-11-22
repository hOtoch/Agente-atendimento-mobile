"""`estoque_local.erp_produto_id`: gravado e lido; linhas sem id continuam validas."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.outbound.db.config import RepositorioEstoqueLocalSql, RepositorioLojasSql
from app.application.config.modelos import LinhaEstoqueLocal
from app.domain.estoque import Condicao
from app.domain.valores import Capacidade, Dinheiro, ModeloAparelho

pytestmark = pytest.mark.integration


def _linha(sku: str, erp_id: int | None = None) -> LinhaEstoqueLocal:
    return LinhaEstoqueLocal(
        sku=sku,
        modelo=ModeloAparelho.de("iPhone 15", "Apple"),
        capacidade=Capacidade("128gb"),
        cor="Preto",
        condicao=Condicao.NOVO,
        preco_pix=Dinheiro.de(Decimal("4199")),
        quantidade=1,
        bateria_pct=None,
        erp_produto_id=erp_id,
    )


async def test_ida_e_volta_do_id_do_erp_e_linha_sem_id(session: AsyncSession) -> None:
    loja_id = await RepositorioLojasSql(session).criar("L")
    repo = RepositorioEstoqueLocalSql(session)
    await repo.substituir(loja_id, [_linha("A", 9_000_000_001), _linha("B")])
    await session.commit()
    lidas = await repo.listar(loja_id)
    assert [(x.sku, x.erp_produto_id) for x in lidas] == [("A", 9_000_000_001), ("B", None)]


def test_linha_do_importador_xlsx_nao_precisa_do_id() -> None:
    assert (
        LinhaEstoqueLocal(
            sku="X",
            modelo=ModeloAparelho.de("iPhone 15", "Apple"),
            capacidade=Capacidade("128gb"),
            cor="Preto",
            condicao=Condicao.NOVO,
            preco_pix=Dinheiro.de(Decimal("1")),
            quantidade=1,
            bateria_pct=None,
        ).erp_produto_id
        is None
    )
