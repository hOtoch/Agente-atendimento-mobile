"""Seed da loja demo: `uv run python -m app.infra.seed [--database-url ...]`.

Cria ou atualiza a "Loja Demo Celulares" (ID fixo `LOJA_DEMO_ID`). Perfil, preco, taxas, troca e
estoque passam pelos casos de uso (mesma validacao do painel); vendedores sao gravados direto
(ainda nao ha caso de uso). Idempotente: rodar de novo atualiza os valores, sem duplicar.
"""

from __future__ import annotations

import argparse
import asyncio
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.outbound.db.config import (
    RepositorioConfigLojaSql,
    RepositorioEstoqueLocalSql,
    RepositorioLojasSql,
    RepositorioMapeamentoSkuSql,
    RepositorioVendedoresSql,
)
from app.adapters.outbound.db.models import Loja, Vendedor
from app.adapters.outbound.db.session import criar_engine, criar_session_factory
from app.application.config.casos_de_uso import CasosDeUsoConfig
from app.application.config.modelos import ErroCampo, ErrosDeValidacao
from app.application.config.portas import SemIntegracaoEstoque
from app.application.config.validacao import validar_pesos_vendedores
from app.infra.seed_data.estoque import ESTOQUE
from app.infra.seed_data.pagamento import PAGAMENTO
from app.infra.seed_data.perfil import NOME_LOJA, PERFIL
from app.infra.seed_data.preco import PRECO
from app.infra.seed_data.taxas import TAXAS
from app.infra.seed_data.troca import TROCA
from app.infra.seed_data.vendedores import VENDEDORES
from app.infra.settings import get_settings

LOJA_DEMO_ID = uuid.UUID("00000000-0000-4000-8000-00000000de30")


@dataclass(frozen=True, slots=True)
class ResumoSeed:
    loja_id: uuid.UUID
    vendedores: int
    taxas: int
    linhas_troca: int
    itens_estoque: int
    checklist_completo: bool


async def aplicar_dados(casos: CasosDeUsoConfig, loja_id: uuid.UUID) -> None:
    """Grava perfil, preco, pagamento, taxas, troca e estoque pelos casos de uso (valida igual)."""
    await casos.atualizar_perfil(loja_id, PERFIL)
    await casos.atualizar_preco(loja_id, PRECO)
    await casos.atualizar_pagamento(loja_id, PAGAMENTO)
    await casos.atualizar_taxas(loja_id, TAXAS)
    await casos.atualizar_troca(loja_id, TROCA)
    await casos.atualizar_estoque(loja_id, ESTOQUE)


async def _garantir_loja(session: AsyncSession) -> None:
    loja = await session.get(Loja, LOJA_DEMO_ID)
    if loja is None:
        session.add(Loja(id=LOJA_DEMO_ID, nome=NOME_LOJA))
    else:
        loja.nome = NOME_LOJA
    await session.flush()


async def _gravar_vendedores(session: AsyncSession) -> None:
    pesos: Sequence[Decimal] = [v.peso_percentual for v in VENDEDORES]
    erros: list[ErroCampo] = validar_pesos_vendedores(pesos)
    if erros:
        raise ErrosDeValidacao(erros)
    ids = {v.id for v in VENDEDORES}
    for dados in VENDEDORES:
        vendedor = await session.get(Vendedor, dados.id)
        if vendedor is None:
            vendedor = Vendedor(id=dados.id, loja_id=LOJA_DEMO_ID)
            session.add(vendedor)
        vendedor.loja_id = LOJA_DEMO_ID
        vendedor.nome = dados.nome
        vendedor.telefone = dados.telefone
        vendedor.peso_percentual = dados.peso_percentual
        vendedor.ativo = dados.ativo
    # outros vendedores da loja demo saem da distribuicao (sem apagar: podem ter leads)
    outros = await session.execute(
        select(Vendedor).where(Vendedor.loja_id == LOJA_DEMO_ID, Vendedor.id.not_in(ids))
    )
    for extra in outros.scalars():
        extra.ativo = False
    await session.flush()


def _casos(session: AsyncSession) -> CasosDeUsoConfig:
    return CasosDeUsoConfig(
        lojas=RepositorioLojasSql(session),
        config=RepositorioConfigLojaSql(session),
        estoque=RepositorioEstoqueLocalSql(session),
        mapeamento=RepositorioMapeamentoSkuSql(session),
        vendedores=RepositorioVendedoresSql(session),
        integracao=SemIntegracaoEstoque(),
    )


async def semear(database_url: str) -> ResumoSeed:
    """Cria/atualiza a loja demo no banco indicado, numa unica transacao."""
    engine = criar_engine(database_url)
    try:
        async with criar_session_factory(engine)() as session:
            try:
                await _garantir_loja(session)
                await _gravar_vendedores(session)
                casos = _casos(session)
                await aplicar_dados(casos, LOJA_DEMO_ID)
                checklist = await casos.checklist(LOJA_DEMO_ID)
                await session.commit()
            except BaseException:
                await session.rollback()
                raise
    finally:
        await engine.dispose()
    return ResumoSeed(
        loja_id=LOJA_DEMO_ID,
        vendedores=len(VENDEDORES),
        taxas=len(TAXAS),
        linhas_troca=len(TROCA),
        itens_estoque=len(ESTOQUE),
        checklist_completo=all(i.completo for i in checklist),
    )


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Cria ou atualiza a loja demo.")
    parser.add_argument(
        "--database-url",
        default=None,
        help="URL async do Postgres (padrao: DATABASE_URL do ambiente/.env).",
    )
    args = parser.parse_args(argv)
    url = args.database_url or get_settings().database_url
    resumo = asyncio.run(semear(url))
    print(
        f"Loja demo {resumo.loja_id}: {resumo.vendedores} vendedores, {resumo.taxas} taxas, "
        f"{resumo.linhas_troca} linhas de troca, {resumo.itens_estoque} itens de estoque; "
        f"checklist {'completo' if resumo.checklist_completo else 'INCOMPLETO'}."
    )


if __name__ == "__main__":
    main()
