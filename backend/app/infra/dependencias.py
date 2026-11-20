"""Injecao de dependencias do FastAPI: sessao do banco e casos de uso."""

from collections.abc import AsyncIterator
from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.adapters.outbound.db.config import (
    LeitorVendedoresSql,
    RepositorioConfigLojaSql,
    RepositorioEstoqueLocalSql,
    RepositorioLojasSql,
    RepositorioMapeamentoSkuSql,
)
from app.adapters.outbound.db.session import criar_engine, criar_session_factory
from app.application.config.casos_de_uso import CasosDeUsoConfig
from app.application.config.portas import SemIntegracaoEstoque
from app.infra.settings import get_settings


@lru_cache
def _factory() -> async_sessionmaker[AsyncSession]:
    return criar_session_factory(criar_engine(get_settings().database_url))


async def get_session() -> AsyncIterator[AsyncSession]:
    """Sessao por requisicao. Quem grava chama `await session.commit()` antes de responder."""
    async with _factory()() as session:
        try:
            yield session
        except BaseException:
            await session.rollback()
            raise


def get_casos_config(session: Annotated[AsyncSession, Depends(get_session)]) -> CasosDeUsoConfig:
    return CasosDeUsoConfig(
        lojas=RepositorioLojasSql(session),
        config=RepositorioConfigLojaSql(session),
        estoque=RepositorioEstoqueLocalSql(session),
        mapeamento=RepositorioMapeamentoSkuSql(session),
        vendedores=LeitorVendedoresSql(session),
        integracao=SemIntegracaoEstoque(),
    )
