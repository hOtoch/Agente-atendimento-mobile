"""Injecao de dependencias do FastAPI: sessao do banco e casos de uso."""

import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from functools import lru_cache
from typing import Annotated
from uuid import UUID

from fastapi import Depends
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.adapters.outbound.barramento.redis import BarramentoRedis
from app.adapters.outbound.db.config import (
    LeitorVendedoresSql,
    RepositorioConfigLojaSql,
    RepositorioEstoqueLocalSql,
    RepositorioLojasSql,
    RepositorioMapeamentoSkuSql,
)
from app.adapters.outbound.db.conversas import RepositorioConversasSql
from app.adapters.outbound.db.session import criar_engine, criar_session_factory
from app.application.canal import BarramentoMensagens, ReceberMensagem
from app.adapters.outbound.planilhas.leitor import LeitorXlsx
from app.adapters.outbound.planilhas.modelos_xlsx import GeradorModeloXlsx
from app.application.config.casos_de_uso import CasosDeUsoConfig
from app.application.config.portas import RepositorioLojas, SemIntegracaoEstoque
from app.application.importacao.importar import ImportarPlanilha
from app.application.importacao.portas import GeradorModelo
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


def montar_casos_config(session: AsyncSession) -> CasosDeUsoConfig:
    return CasosDeUsoConfig(
        lojas=RepositorioLojasSql(session),
        config=RepositorioConfigLojaSql(session),
        estoque=RepositorioEstoqueLocalSql(session),
        mapeamento=RepositorioMapeamentoSkuSql(session),
        vendedores=LeitorVendedoresSql(session),
        integracao=SemIntegracaoEstoque(),
    )


def get_casos_config(session: Annotated[AsyncSession, Depends(get_session)]) -> CasosDeUsoConfig:
    return montar_casos_config(session)


def get_importador(session: Annotated[AsyncSession, Depends(get_session)]) -> ImportarPlanilha:
    """Importador na sessao da requisicao: uma transacao, commit so apos validar e gravar tudo."""
    return ImportarPlanilha(
        montar_casos_config(session),
        LeitorXlsx(),
        commit=session.commit,
        rollback=session.rollback,
    )


logger = logging.getLogger(__name__)


@lru_cache
def _redis() -> Redis:
    return Redis.from_url(get_settings().redis_url)


def get_barramento() -> BarramentoMensagens:
    """Barramento de mensagens (Redis pub/sub a partir de `REDIS_URL`), entre processos."""
    return BarramentoRedis(_redis())


def get_lojas(session: Annotated[AsyncSession, Depends(get_session)]) -> RepositorioLojas:
    return RepositorioLojasSql(session)


def get_agendar() -> Callable[[UUID], Awaitable[None]]:
    """PLACEHOLDER: so registra em log. O orquestrador troca pelo `agendar` da fila.

    Contrato: `agendar(conversa_id)` enfileira o atendimento da conversa para o worker e
    precisa ser rapido (a rota de entrada responde 202 sem esperar o processamento).
    """

    async def agendar(conversa_id: UUID) -> None:
        logger.info("conversa agendada (placeholder, sem fila): %s", conversa_id)

    return agendar


def get_receber_mensagem(
    session: Annotated[AsyncSession, Depends(get_session)],
    agendar: Annotated[Callable[[UUID], Awaitable[None]], Depends(get_agendar)],
) -> ReceberMensagem:
    return ReceberMensagem(RepositorioConversasSql(session), agendar)


def get_gerador_modelo() -> GeradorModelo:
    return GeradorModeloXlsx()
