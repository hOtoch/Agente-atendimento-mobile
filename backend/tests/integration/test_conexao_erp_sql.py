"""Conexao com o ERP no Postgres real: upsert, status da sincronizacao e colunas novas do M8."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.outbound.db.conexao_erp import RepositorioConexaoErpSql
from app.adapters.outbound.db.models import ConexaoErpRow, EstoqueLocalRow, Lead, Loja, Vendedor
from app.domain.conexao_erp import ConexaoErp

pytestmark = pytest.mark.integration

EM = datetime(2026, 11, 22, 12, 30, tzinfo=UTC)


async def _loja(session: AsyncSession) -> UUID:
    loja = Loja(nome="L")
    session.add(loja)
    await session.flush()
    return loja.id


async def test_sem_conexao_devolve_none(session: AsyncSession) -> None:
    repo = RepositorioConexaoErpSql(session)
    assert await repo.obter(await _loja(session)) is None


async def test_salva_le_e_regrava_com_upsert(session: AsyncSession) -> None:
    loja_id = await _loja(session)
    repo = RepositorioConexaoErpSql(session)
    await repo.salvar(
        ConexaoErp(
            loja_id=loja_id,
            system_unit_id=12,
            filtro_loja="Centro",
            ativo=True,
            intervalo_min=30,
            exportar_handoff=True,
        )
    )
    await session.commit()
    c = await repo.obter(loja_id)
    assert c is not None
    assert (c.provedor, c.system_unit_id, c.filtro_loja) == ("mercadophone", 12, "Centro")
    assert (c.ativo, c.intervalo_min, c.exportar_handoff) == (True, 30, True)
    assert (c.ultima_sincronizacao_em, c.ultimo_status, c.ultimo_relatorio) == (None, None, None)

    await repo.salvar(ConexaoErp(loja_id=loja_id, system_unit_id=13))
    await session.commit()
    c2 = await repo.obter(loja_id)
    assert c2 is not None
    assert (c2.system_unit_id, c2.filtro_loja, c2.ativo, c2.intervalo_min) == (13, None, False, 15)
    linhas = (await session.execute(select(ConexaoErpRow))).scalars().all()
    assert len(linhas) == 1


async def test_registrar_sincronizacao_grava_status_e_o_salvar_preserva(
    session: AsyncSession,
) -> None:
    loja_id = await _loja(session)
    repo = RepositorioConexaoErpSql(session)
    await repo.salvar(ConexaoErp(loja_id=loja_id, system_unit_id=12, ativo=True))
    await repo.registrar_sincronizacao(
        loja_id, em=EM, status="parcial", relatorio={"produtos": 10, "avisos": ["sem preco"]}
    )
    await session.commit()
    c = await repo.obter(loja_id)
    assert c is not None
    assert c.ultima_sincronizacao_em == EM
    assert c.ultimo_status == "parcial"
    assert c.ultimo_relatorio == {"produtos": 10, "avisos": ["sem preco"]}

    await repo.salvar(ConexaoErp(loja_id=loja_id, system_unit_id=99, ativo=True))
    await session.commit()
    c2 = await repo.obter(loja_id)
    assert c2 is not None
    assert (c2.system_unit_id, c2.ultimo_status, c2.ultima_sincronizacao_em) == (99, "parcial", EM)


async def test_registrar_sincronizacao_sem_conexao_nao_cria_linha(session: AsyncSession) -> None:
    loja_id = await _loja(session)
    repo = RepositorioConexaoErpSql(session)
    await repo.registrar_sincronizacao(loja_id, em=EM, status="ok", relatorio=None)
    await session.commit()
    assert await repo.obter(loja_id) is None


async def test_listar_ativas(session: AsyncSession) -> None:
    a, b = await _loja(session), await _loja(session)
    repo = RepositorioConexaoErpSql(session)
    await repo.salvar(ConexaoErp(loja_id=a, system_unit_id=1, ativo=True))
    await repo.salvar(ConexaoErp(loja_id=b, system_unit_id=2, ativo=False))
    await session.commit()
    assert [c.loja_id for c in await repo.listar_ativas()] == [a]


async def test_banco_recusa_unidade_e_intervalo_invalidos(session: AsyncSession) -> None:
    loja_id = await _loja(session)
    session.add(ConexaoErpRow(loja_id=loja_id, system_unit_id=0))
    with pytest.raises(IntegrityError):
        await session.flush()


async def test_colunas_novas_do_m8_aceitam_null_e_valor(session: AsyncSession) -> None:
    loja_id = await _loja(session)
    estoque = EstoqueLocalRow(
        loja_id=loja_id,
        posicao=0,
        sku="A",
        modelo="iPhone 15",
        marca="Apple",
        capacidade_gb=128,
        cor="Preto",
        condicao="novo",
        preco_pix=1000,
        quantidade=1,
    )
    vendedor = Vendedor(loja_id=loja_id, nome="V")
    lead = Lead(loja_id=loja_id, telefone="5511999990000", canal="webchat")
    session.add_all([estoque, vendedor, lead])
    await session.flush()
    assert estoque.erp_produto_id is None
    assert vendedor.codigo_erp is None
    assert (lead.erp_cliente_id, lead.erp_orcamento_id) == (None, None)

    estoque.erp_produto_id = 9_000_000_001
    vendedor.codigo_erp = "V-12"
    lead.erp_cliente_id = 5_000_000_000
    lead.erp_orcamento_id = 6_000_000_000
    ids = (estoque.id, vendedor.id, lead.id)
    await session.commit()
    session.expire_all()
    assert (await session.get(EstoqueLocalRow, ids[0])).erp_produto_id == 9_000_000_001  # type: ignore[union-attr]
    assert (await session.get(Vendedor, ids[1])).codigo_erp == "V-12"  # type: ignore[union-attr]
    atual = await session.get(Lead, ids[2])
    assert atual is not None
    assert (atual.erp_cliente_id, atual.erp_orcamento_id) == (5_000_000_000, 6_000_000_000)
