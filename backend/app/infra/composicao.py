"""Composicao: monta o `ProcessarConversa` real (SQL + LLM + estoque + canal) e o agendador.

API e worker compartilham `criar_agendador` (mesmo prefixo de chaves e mesma janela).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, date, datetime, timedelta, timezone
from uuid import UUID

from arq.connections import ArqRedis
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.adapters.outbound.barramento.painel import PublicadorPainelBarramento
from app.adapters.outbound.barramento.redis import BarramentoRedis
from app.adapters.outbound.canal.webchat import WebChatAdapter
from app.adapters.outbound.db.atendimento import RepositorioAtendimentoSql
from app.adapters.outbound.db.config import (
    RepositorioConfigLojaSql,
    RepositorioEstoqueLocalSql,
    RepositorioLojasSql,
    RepositorioMapeamentoSkuSql,
    RepositorioVendedoresSql,
)
from app.adapters.outbound.db.painel import RepositorioPainelSql
from app.adapters.outbound.db.processamento import RegistroEventosSql, RepositorioProcessamentoSql
from app.adapters.outbound.db.transcricao import RepositorioTranscricaoSql
from app.adapters.outbound.estoque.banco import FonteEstoqueLocalSql
from app.adapters.outbound.estoque.planilha import PlanilhaAdapter
from app.application.agente.ferramentas import CatalogoFerramentas
from app.application.agente.processar_conversa import ProcessarConversa
from app.application.canal import BarramentoMensagens, Canal, CanalPort
from app.application.config.casos_de_uso import CasosDeUsoConfig
from app.application.config.portas import SemIntegracaoEstoque
from app.application.estoque_resiliente import EstoqueResiliente
from app.application.llm import LLMPort
from app.application.painel.casos_de_uso import CasosPainel
from app.application.painel.publicador import PublicadorPainel
from app.infra.fila import AgendadorArq, RelogioParede
from app.infra.llm import criar_llm
from app.infra.settings import Settings, get_settings

PREFIXO_FILA = ""
"""Prefixo das chaves da fila; API e worker precisam usar o mesmo."""

_BRASILIA = timezone(timedelta(hours=-3))  # sem DST desde 2019; evita depender do tzdata


def hoje_brasil() -> date:
    return datetime.now(UTC).astimezone(_BRASILIA).date()


def criar_agendador(redis: ArqRedis, settings: Settings | None = None) -> AgendadorArq:
    settings = settings or get_settings()
    return AgendadorArq(redis, janela_s=settings.fila_janela_s, prefixo=PREFIXO_FILA)


def montar_casos_config(session: AsyncSession) -> CasosDeUsoConfig:
    return CasosDeUsoConfig(
        lojas=RepositorioLojasSql(session),
        config=RepositorioConfigLojaSql(session),
        estoque=RepositorioEstoqueLocalSql(session),
        mapeamento=RepositorioMapeamentoSkuSql(session),
        vendedores=RepositorioVendedoresSql(session),
        integracao=SemIntegracaoEstoque(),
    )


def montar_casos_painel(session: AsyncSession, barramento: BarramentoMensagens) -> CasosPainel:
    """Painel: leitura/gravacao em SQL, eventos pelo barramento e envio pelo webchat."""
    return CasosPainel(
        repo=RepositorioPainelSql(session),
        publicador=PublicadorPainelBarramento(barramento),
        canais={Canal.WEBCHAT: WebChatAdapter(barramento)},
    )


def montar_processar_conversa(
    session: AsyncSession,
    *,
    llm: LLMPort,
    canais: Mapping[Canal, CanalPort],
    painel: PublicadorPainel | None = None,
    hoje: Callable[[], date] = hoje_brasil,
    max_iteracoes: int = 6,
) -> ProcessarConversa:
    """Caso de uso real sobre uma sessao: estoque = banco -> planilha -> resiliente."""
    casos = montar_casos_config(session)
    estoque = EstoqueResiliente(
        PlanilhaAdapter(FonteEstoqueLocalSql(casos.estoque)), RelogioParede()
    )
    return ProcessarConversa(
        conversas=RepositorioProcessamentoSql(session),
        transcricao=RepositorioTranscricaoSql(session),
        atendimento=RepositorioAtendimentoSql(session),
        eventos=RegistroEventosSql(session),
        llm=llm,
        catalogo=CatalogoFerramentas(),
        canais=canais,
        config=casos,
        estoque=estoque,
        hoje=hoje,
        painel=painel,
        max_iteracoes=max_iteracoes,
    )


def criar_processador(
    factory: async_sessionmaker[AsyncSession],
    *,
    redis: Redis,
    settings: Settings | None = None,
    llm: LLMPort | None = None,
    barramento: BarramentoMensagens | None = None,
) -> Callable[[UUID], Awaitable[None]]:
    """`processar(conversa_id)` do worker: uma sessao nova por job, LLM/canal compartilhados."""
    settings = settings or get_settings()
    llm = llm or criar_llm(settings)
    barramento = barramento or BarramentoRedis(redis)
    canais: dict[Canal, CanalPort] = {Canal.WEBCHAT: WebChatAdapter(barramento)}
    painel = PublicadorPainelBarramento(barramento)

    async def processar(conversa_id: UUID) -> None:
        async with factory() as session:
            try:
                await montar_processar_conversa(session, llm=llm, canais=canais, painel=painel)(
                    conversa_id
                )
            except BaseException:
                await session.rollback()
                raise

    return processar
