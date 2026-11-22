"""Composicao: monta o `ProcessarConversa` real (SQL + LLM + estoque + canal) e o agendador.

API e worker compartilham `criar_agendador` (mesmo prefixo de chaves e mesma janela).
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, timedelta, timezone
from uuid import UUID

from arq.connections import ArqRedis
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.adapters.outbound.audio.stt_openai import STTOpenAI
from app.adapters.outbound.audio.stt_openai import criar_cliente_http as criar_cliente_openai
from app.adapters.outbound.audio.tts_openai import TTSOpenAI
from app.adapters.outbound.audio.tts_openai import criar_cliente_http as criar_cliente_tts
from app.adapters.outbound.barramento.painel import PublicadorPainelBarramento
from app.adapters.outbound.barramento.redis import BarramentoRedis
from app.adapters.outbound.canal.enviadas import RegistroEnviadasRedis
from app.adapters.outbound.canal.evolution import EvolutionAdapter
from app.adapters.outbound.canal.evolution_api import EvolutionGateway, criar_cliente_http
from app.adapters.outbound.canal.webchat import WebChatAdapter
from app.adapters.outbound.db.atendimento import RepositorioAtendimentoSql
from app.adapters.outbound.db.conexao_erp import RepositorioConexaoErpSql
from app.adapters.outbound.db.config import (
    RepositorioConfigLojaSql,
    RepositorioEstoqueLocalSql,
    RepositorioLojasSql,
    RepositorioMapeamentoSkuSql,
    RepositorioVendedoresSql,
)
from app.adapters.outbound.db.distribuicao import AtribuicoesLeadSql
from app.adapters.outbound.db.followup import (
    RegistroTentativasSql,
    RepositorioConfigFollowupSql,
    RepositorioFollowupSql,
)
from app.adapters.outbound.db.painel import RepositorioPainelSql
from app.adapters.outbound.db.processamento import RegistroEventosSql, RepositorioProcessamentoSql
from app.adapters.outbound.db.transcricao import RepositorioTranscricaoSql
from app.adapters.outbound.db.vinculo_erp import VinculosErpLeadSql
from app.adapters.outbound.estoque.banco import FonteEstoqueLocalSql
from app.adapters.outbound.estoque.planilha import PlanilhaAdapter
from app.adapters.outbound.mercadophone.fonte import FonteEstoqueMercadoPhone
from app.adapters.outbound.mercadophone.pedido import PedidoMercadoPhone
from app.adapters.outbound.midia.disco import ArmazenamentoMidiaDisco
from app.application.agendamento import TravaConversa
from app.application.agente.ferramentas import CatalogoFerramentas
from app.application.agente.processar_conversa import ProcessarConversa
from app.application.audio_entrada import STTPort, TranscreverAudio
from app.application.audio_saida import ResponderEmAudio
from app.application.canal import BarramentoMensagens, Canal, CanalPort
from app.application.config.casos_de_uso import CasosDeUsoConfig
from app.application.config.portas import SemIntegracaoEstoque
from app.application.distribuir_lead import DistribuirLead
from app.application.estoque_erp import FonteEstoqueErp, SincronizarEstoqueErp
from app.application.estoque_resiliente import EstoqueResiliente
from app.application.exportar_handoff_erp import ExportarHandoffParaErp, ServicosDaExportacao
from app.application.followup import EnviarFollowups, RedatorFollowupLLM
from app.application.handoff import AoSolicitarHandoff, CasosHandoff, GanchosHandoff
from app.application.llm import LLMPort
from app.application.midia import ArmazenamentoMidia
from app.application.notificar_vendedor import NotificarVendedorNoHandoff, ServicosDaDistribuicao
from app.application.painel.casos_de_uso import CasosPainel
from app.application.painel.publicador import PublicadorPainel, PublicadorPainelNulo
from app.application.pedido_erp import DadosHandoff, FalhaPedidoErp, PedidoPort, RegistroErp
from app.application.whatsapp import RegistroEnviadas, WhatsAppGateway
from app.domain.conexao_erp import ConexaoErp
from app.infra.fila import AgendadorArq, RelogioParede, TravaRedis
from app.infra.llm import criar_llm
from app.infra.mercadophone import MercadoPhoneNaoConfigurado, get_cliente_mercadophone
from app.infra.relogio import RelogioSistema
from app.infra.settings import Settings, get_settings

log = logging.getLogger(__name__)

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


class _PedidoErpDesligado:
    """`PedidoPort` de quando o servidor nao tem a chave do ERP: falha tipada, sem rede."""

    async def registrar_handoff(self, conexao: ConexaoErp, dados: DadosHandoff) -> RegistroErp:
        raise FalhaPedidoErp("MERCADOPHONE_API_KEY não configurada: nada foi enviado ao ERP")


def criar_pedido_erp() -> PedidoPort:
    """Pedido no Mercado Phone; sem `MERCADOPHONE_API_KEY` devolve um que falha com erro tipado."""
    try:
        return PedidoMercadoPhone(get_cliente_mercadophone())
    except MercadoPhoneNaoConfigurado:
        log.info("exportacao do handoff ao ERP sem efeito: MERCADOPHONE_API_KEY nao configurada")
        return _PedidoErpDesligado()


def montar_exportar_handoff_erp(
    factory: async_sessionmaker[AsyncSession], *, pedido: PedidoPort | None = None
) -> ExportarHandoffParaErp:
    """Gancho que exporta o lead ao ERP (cliente + orcamento); so age com `exportar_handoff` ligado.

    Sessoes proprias e curtas (ler; depois gravar ids e evento): a chamada ao ERP nao segura
    transacao.
    """

    @asynccontextmanager
    async def abrir() -> AsyncIterator[ServicosDaExportacao]:
        async with factory() as session:
            try:
                yield ServicosDaExportacao(
                    conexoes=RepositorioConexaoErpSql(session),
                    repo=RepositorioPainelSql(session),
                    vendedores=RepositorioVendedoresSql(session),
                    estoque=RepositorioEstoqueLocalSql(session),
                    vinculos=VinculosErpLeadSql(session),
                )
                await session.commit()
            except BaseException:
                await session.rollback()
                raise

    return ExportarHandoffParaErp(abrir=abrir, pedido=pedido or criar_pedido_erp())


def montar_gancho_handoff(
    factory: async_sessionmaker[AsyncSession],
    *,
    gateway: WhatsAppGateway,
    registro: RegistroEnviadas,
    publicador: PublicadorPainel,
    pedido: PedidoPort | None = None,
    settings: Settings | None = None,
) -> GanchosHandoff:
    """Gancho completo do handoff: avisa o vendedor e, DEPOIS da atribuicao, exporta ao ERP."""
    return GanchosHandoff(
        [
            montar_aviso_handoff(
                factory,
                gateway=gateway,
                registro=registro,
                publicador=publicador,
                settings=settings,
            ),
            montar_exportar_handoff_erp(factory, pedido=pedido),
        ]
    )


def criar_gancho_handoff(
    factory: async_sessionmaker[AsyncSession],
    *,
    redis: Redis,
    barramento: BarramentoMensagens | None = None,
    settings: Settings | None = None,
) -> GanchosHandoff:
    """`montar_gancho_handoff` com Evolution, painel em tempo real e Mercado Phone reais."""
    settings = settings or get_settings()
    return GanchosHandoff(
        [
            criar_aviso_handoff(factory, redis=redis, barramento=barramento, settings=settings),
            montar_exportar_handoff_erp(factory),
        ]
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


def criar_resposta_em_audio(settings: Settings | None = None) -> ResponderEmAudio | None:
    """TTS da OpenAI + midia em disco; `None` (so texto) quando nao ha `OPENAI_API_KEY`."""
    settings = settings or get_settings()
    if not settings.openai_api_key:
        return None
    tts = TTSOpenAI(
        criar_cliente_tts(),
        api_key=settings.openai_api_key,
        modelo=settings.tts_model,
        voz=settings.tts_voz,
    )
    return ResponderEmAudio(
        tts, ArmazenamentoMidiaDisco(settings.midia_dir), base_midia=settings.api_publica_url
    )


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
    audio_saida: ResponderEmAudio | None = None,
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
        audio_saida=audio_saida,
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
    canais = _criar_canais(redis, barramento, settings)
    painel = PublicadorPainelBarramento(barramento)
    midia = ArmazenamentoMidiaDisco(settings.midia_dir)
    transcrever = criar_transcritor(settings, stt)
    audio_saida = criar_resposta_em_audio(settings)

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
                    audio_saida=audio_saida,
                )(conversa_id)
            except BaseException:
                await session.rollback()
                raise

    return processar


def agora_utc() -> datetime:
    return datetime.now(UTC)


def montar_enviar_followups(
    session: AsyncSession,
    *,
    llm: LLMPort,
    canais: Mapping[Canal, CanalPort],
    painel: PublicadorPainel | None = None,
    trava: TravaConversa | None = None,
    agora: Callable[[], datetime] = agora_utc,
) -> EnviarFollowups:
    """Rodada de follow-up automatico sobre uma sessao (SQL + LLM so para redigir o texto)."""
    followups = RepositorioFollowupSql(session)
    return EnviarFollowups(
        configs=RepositorioConfigFollowupSql(session),
        leads=followups,
        redator=RedatorFollowupLLM(
            llm=llm,
            config=montar_casos_config(session),
            atendimento=RepositorioAtendimentoSql(session),
            transcricao=RepositorioTranscricaoSql(session),
            agora=agora,
        ),
        tentativas=RegistroTentativasSql(session),
        saidas=RepositorioProcessamentoSql(session),
        transcricao=RepositorioTranscricaoSql(session),
        canais=canais,
        agora=agora,
        painel=painel,
        trava=trava,
    )


def criar_followups(
    factory: async_sessionmaker[AsyncSession],
    *,
    redis: ArqRedis,
    settings: Settings | None = None,
    llm: LLMPort | None = None,
    barramento: BarramentoMensagens | None = None,
    agora: Callable[[], datetime] = agora_utc,
) -> Callable[[], Awaitable[int]]:
    """`followups()` do cron do worker: uma sessao nova por rodada; devolve quantos enviou."""
    settings = settings or get_settings()
    llm = llm or criar_llm(settings)
    barramento = barramento or BarramentoRedis(redis)
    canais = _criar_canais(redis, barramento, settings)
    painel = PublicadorPainelBarramento(barramento)

    async def followups() -> int:
        async with factory() as session:
            try:
                return await montar_enviar_followups(
                    session,
                    llm=llm,
                    canais=canais,
                    painel=painel,
                    trava=TravaRedis(redis),
                    agora=agora,
                )()
            except BaseException:
                await session.rollback()
                raise

    return followups


def _criar_canais(
    redis: Redis, barramento: BarramentoMensagens, settings: Settings
) -> dict[Canal, CanalPort]:
    return {
        Canal.WEBCHAT: WebChatAdapter(barramento),
        Canal.WHATSAPP: criar_canal_whatsapp(
            criar_gateway_whatsapp(settings), RegistroEnviadasRedis(redis), settings
        ),
    }


def montar_sincronizar_estoque_erp(
    session: AsyncSession,
    fonte: FonteEstoqueErp,
    *,
    agora: Callable[[], datetime] = agora_utc,
) -> SincronizarEstoqueErp:
    """Sincronizacao do estoque do ERP sobre uma sessao; o caso de uso commita por loja."""
    return SincronizarEstoqueErp(
        RepositorioConexaoErpSql(session),
        RepositorioEstoqueLocalSql(session),
        fonte,
        relogio=RelogioSistema(),
        agora=agora,
        commit=session.commit,
        rollback=session.rollback,
    )


def criar_sincronizador_erp(
    factory: async_sessionmaker[AsyncSession],
    *,
    fonte: FonteEstoqueErp | None = None,
    agora: Callable[[], datetime] = agora_utc,
) -> Callable[[], Awaitable[int]]:
    """`sincronizar()` do cron do worker: uma sessao nova por rodada; devolve quantas lojas rodou.

    Sem `MERCADOPHONE_API_KEY` no servidor a integracao esta desligada: a rodada nao faz nada
    (um aviso no log, so na primeira vez).
    """
    avisou = False

    def _fonte() -> FonteEstoqueErp | None:
        nonlocal avisou
        if fonte is not None:
            return fonte
        try:
            return FonteEstoqueMercadoPhone(get_cliente_mercadophone())
        except MercadoPhoneNaoConfigurado:
            if not avisou:
                avisou = True
                log.info("sincronizacao do ERP desligada: MERCADOPHONE_API_KEY nao configurada")
            return None

    async def sincronizar() -> int:
        origem = _fonte()
        if origem is None:
            return 0
        async with factory() as session:
            try:
                resultados = await montar_sincronizar_estoque_erp(
                    session, origem, agora=agora
                ).sincronizar_vencidas()
            except BaseException:
                await session.rollback()
                raise
        for r in resultados:
            log.info(
                "estoque do ERP: loja %s %s (%s)", r.loja_id, r.status, r.relatorio.get("erro", "")
            )
        return len(resultados)

    return sincronizar
