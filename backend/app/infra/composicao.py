"""Composicao: monta o `ProcessarConversa` real (SQL + LLM + estoque + canal) e o agendador.

API e worker compartilham `criar_agendador` (mesmo prefixo de chaves e mesma janela).
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, timedelta, timezone
from uuid import UUID

from arq.connections import ArqRedis
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.adapters.outbound.audio.stt_openai import STTOpenAI
from app.adapters.outbound.audio.stt_openai import criar_cliente_http as criar_cliente_openai
from app.adapters.outbound.barramento.painel import PublicadorPainelBarramento
from app.adapters.outbound.barramento.redis import BarramentoRedis
from app.adapters.outbound.canal.enviadas import RegistroEnviadasRedis
from app.adapters.outbound.canal.evolution import EvolutionAdapter
from app.adapters.outbound.canal.evolution_api import EvolutionGateway, criar_cliente_http
from app.adapters.outbound.canal.webchat import WebChatAdapter
from app.adapters.outbound.db.atendimento import RepositorioAtendimentoSql
from app.adapters.outbound.db.config import (
    RepositorioConfigLojaSql,
    RepositorioEstoqueLocalSql,
    RepositorioLojasSql,
    RepositorioMapeamentoSkuSql,
    RepositorioVendedoresSql,
)
from app.adapters.outbound.db.distribuicao import AtribuicoesLeadSql
from app.adapters.outbound.db.painel import RepositorioPainelSql
from app.adapters.outbound.db.processamento import RegistroEventosSql, RepositorioProcessamentoSql
from app.adapters.outbound.db.transcricao import RepositorioTranscricaoSql
from app.adapters.outbound.estoque.banco import FonteEstoqueLocalSql
from app.adapters.outbound.estoque.planilha import PlanilhaAdapter
from app.adapters.outbound.midia.disco import ArmazenamentoMidiaDisco
from app.application.agente.ferramentas import CatalogoFerramentas
from app.application.agente.processar_conversa import ProcessarConversa
from app.application.audio_entrada import STTPort, TranscreverAudio
from app.application.canal import BarramentoMensagens, Canal, CanalPort
from app.application.config.casos_de_uso import CasosDeUsoConfig
from app.application.config.portas import SemIntegracaoEstoque
from app.application.distribuir_lead import DistribuirLead
from app.application.estoque_resiliente import EstoqueResiliente
from app.application.handoff import AoSolicitarHandoff, CasosHandoff
from app.application.llm import LLMPort
from app.application.midia import ArmazenamentoMidia
from app.application.notificar_vendedor import NotificarVendedorNoHandoff, ServicosDaDistribuicao
from app.application.painel.casos_de_uso import CasosPainel
from app.application.painel.publicador import PublicadorPainel, PublicadorPainelNulo
from app.application.whatsapp import RegistroEnviadas, WhatsAppGateway
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


def montar_distribuir_lead(session: AsyncSession) -> DistribuirLead:
    """Distribuicao de leads por porcentagem sobre uma sessao.

    Nao faz commit: o chamador (handoff) commita; a trava por loja dura ate la.
    """
    return DistribuirLead(RepositorioVendedoresSql(session), AtribuicoesLeadSql(session))


def montar_aviso_handoff(
    factory: async_sessionmaker[AsyncSession],
    *,
    gateway: WhatsAppGateway,
    registro: RegistroEnviadas,
    publicador: PublicadorPainel,
    settings: Settings | None = None,
) -> NotificarVendedorNoHandoff:
    """Gancho do handoff: distribui o lead, atribui o dono e avisa o vendedor no WhatsApp.

    A distribuicao roda numa sessao PROPRIA (commit ao fim; a trava da loja nao dura durante o
    envio HTTP), por isso recebe a `factory` e nao a sessao do atendimento.
    """
    settings = settings or get_settings()

    @asynccontextmanager
    async def abrir() -> AsyncIterator[ServicosDaDistribuicao]:
        async with factory() as session:
            try:
                yield ServicosDaDistribuicao(
                    distribuir=montar_distribuir_lead(session),
                    repo=RepositorioPainelSql(session),
                    vendedores=RepositorioVendedoresSql(session),
                )
                await session.commit()  # solta a trava da loja (tambem sem mudancas)
            except BaseException:
                await session.rollback()
                raise

    return NotificarVendedorNoHandoff(
        abrir=abrir,
        gateway=gateway,
        registro=registro,
        publicador=publicador,
        url_painel=settings.painel_url,
    )


def criar_aviso_handoff(
    factory: async_sessionmaker[AsyncSession],
    *,
    redis: Redis,
    barramento: BarramentoMensagens | None = None,
    settings: Settings | None = None,
) -> NotificarVendedorNoHandoff:
    """`montar_aviso_handoff` com Evolution, registro de enviadas e painel em tempo real reais."""
    settings = settings or get_settings()
    return montar_aviso_handoff(
        factory,
        gateway=criar_gateway_whatsapp(settings),
        registro=RegistroEnviadasRedis(redis),
        publicador=PublicadorPainelBarramento(barramento or BarramentoRedis(redis)),
        settings=settings,
    )


def montar_casos_handoff(
    session: AsyncSession,
    *,
    publicador: PublicadorPainel,
    llm: LLMPort | None = None,
    aviso: AoSolicitarHandoff | None = None,
) -> CasosHandoff:
    """Handoff em SQL. `aviso` e o gancho `AoSolicitarHandoff` (nulo por padrao)."""
    return CasosHandoff(
        repo=RepositorioPainelSql(session),
        publicador=publicador,
        transcricao=RepositorioTranscricaoSql(session),
        atendimento=RepositorioAtendimentoSql(session),
        llm=llm,
        aviso=aviso,
    )


def criar_gateway_whatsapp(settings: Settings | None = None) -> EvolutionGateway:
    """Cliente da Evolution (um `httpx.AsyncClient` por chamada: o dono decide o ciclo de vida)."""
    settings = settings or get_settings()
    return EvolutionGateway(
        criar_cliente_http(settings.evolution_api_url, settings.evolution_api_key),
        webhook_url=settings.evolution_webhook_url,
        webhook_token=settings.evolution_webhook_token,
    )


def criar_canal_whatsapp(
    gateway: WhatsAppGateway, registro: RegistroEnviadas, settings: Settings | None = None
) -> EvolutionAdapter:
    settings = settings or get_settings()
    return EvolutionAdapter(
        gateway,
        registro,
        armazenamento=ArmazenamentoMidiaDisco(settings.midia_dir),
        base_midia=settings.api_publica_url,
    )


def criar_transcritor(
    settings: Settings | None = None, stt: STTPort | None = None
) -> TranscreverAudio:
    """Transcricao do audio de entrada: STT da OpenAI (sem chave, toda tentativa vira falha)."""
    settings = settings or get_settings()
    stt = stt or STTOpenAI(
        criar_cliente_openai(), api_key=settings.openai_api_key, modelo=settings.stt_model
    )
    return TranscreverAudio(stt, ArmazenamentoMidiaDisco(settings.midia_dir))


def montar_casos_painel(
    session: AsyncSession,
    barramento: BarramentoMensagens,
    *,
    whatsapp: CanalPort | None = None,
) -> CasosPainel:
    """Painel: leitura/gravacao em SQL, eventos pelo barramento e envio por webchat/WhatsApp."""
    canais: dict[Canal, CanalPort] = {Canal.WEBCHAT: WebChatAdapter(barramento)}
    if whatsapp is not None:
        canais[Canal.WHATSAPP] = whatsapp
    publicador = PublicadorPainelBarramento(barramento)
    return CasosPainel(
        repo=RepositorioPainelSql(session),
        publicador=publicador,
        handoff=montar_casos_handoff(session, publicador=publicador),
        canais=canais,
    )


def montar_processar_conversa(
    session: AsyncSession,
    *,
    llm: LLMPort,
    canais: Mapping[Canal, CanalPort],
    painel: PublicadorPainel | None = None,
    aviso_handoff: AoSolicitarHandoff | None = None,
    hoje: Callable[[], date] = hoje_brasil,
    transcrever_audio: TranscreverAudio | None = None,
    max_iteracoes: int = 6,
    midia: ArmazenamentoMidia | None = None,
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
        handoff=montar_casos_handoff(
            session,
            publicador=painel or PublicadorPainelNulo(),
            llm=llm,
            aviso=aviso_handoff,
        ),
        transcrever_audio=transcrever_audio,
        max_iteracoes=max_iteracoes,
        midia=midia,
    )


def criar_processador(
    factory: async_sessionmaker[AsyncSession],
    *,
    redis: Redis,
    settings: Settings | None = None,
    llm: LLMPort | None = None,
    barramento: BarramentoMensagens | None = None,
    aviso_handoff: AoSolicitarHandoff | None = None,
    stt: STTPort | None = None,
) -> Callable[[UUID], Awaitable[None]]:
    """`processar(conversa_id)` do worker: uma sessao nova por job, LLM/canal compartilhados."""
    settings = settings or get_settings()
    llm = llm or criar_llm(settings)
    barramento = barramento or BarramentoRedis(redis)
    canais: dict[Canal, CanalPort] = {
        Canal.WEBCHAT: WebChatAdapter(barramento),
        Canal.WHATSAPP: criar_canal_whatsapp(
            criar_gateway_whatsapp(settings), RegistroEnviadasRedis(redis), settings
        ),
    }
    painel = PublicadorPainelBarramento(barramento)
    midia = ArmazenamentoMidiaDisco(settings.midia_dir)
    transcrever = criar_transcritor(settings, stt)

    async def processar(conversa_id: UUID) -> None:
        async with factory() as session:
            try:
                await montar_processar_conversa(
                    session,
                    llm=llm,
                    canais=canais,
                    painel=painel,
                    aviso_handoff=aviso_handoff,
                    midia=midia,
                    transcrever_audio=transcrever,
                )(conversa_id)
            except BaseException:
                await session.rollback()
                raise

    return processar
