"""Injecao de dependencias do FastAPI: sessao do banco e casos de uso."""

from collections.abc import AsyncIterator, Awaitable, Callable
from functools import lru_cache
from typing import Annotated, cast
from uuid import UUID

from arq.connections import ArqRedis
from fastapi import Cookie, Depends
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.adapters.outbound.auth.hasher import HasherSenhaArgon2
from app.adapters.outbound.auth.sessoes import SessoesRedis
from app.adapters.outbound.auth.usuarios import RepositorioUsuariosSql
from app.adapters.outbound.barramento.painel import PublicadorPainelBarramento
from app.adapters.outbound.barramento.redis import BarramentoRedis
from app.adapters.outbound.canal.enviadas import RegistroEnviadasRedis
from app.adapters.outbound.canal.evolution import EvolutionAdapter
from app.adapters.outbound.canal.evolution_api import EvolutionGateway
from app.adapters.outbound.db.conexao_erp import RepositorioConexaoErpSql
from app.adapters.outbound.db.config import RepositorioLojasSql, RepositorioVendedoresSql
from app.adapters.outbound.db.conversas import RepositorioConversasSql
from app.adapters.outbound.db.followup import RepositorioConfigFollowupSql
from app.adapters.outbound.db.metricas import LeitorMetricasSql
from app.adapters.outbound.db.painel import RepositorioPainelSql
from app.adapters.outbound.db.session import criar_engine, criar_session_factory
from app.adapters.outbound.mercadophone.fonte import FonteEstoqueMercadoPhone
from app.adapters.outbound.mercadophone.vendedores import LeitorVendedoresMercadoPhone
from app.adapters.outbound.midia.disco import ArmazenamentoMidiaDisco
from app.adapters.outbound.planilhas.leitor import LeitorXlsx
from app.adapters.outbound.planilhas.modelos_xlsx import GeradorModeloXlsx
from app.application.auth.modelos import SessaoAtual, SessaoInvalida
from app.application.auth.portas import HasherSenha, RepositorioUsuarios, Sessoes
from app.application.canal import BarramentoMensagens, ReceberMensagem
from app.application.config.casos_de_uso import CasosDeUsoConfig
from app.application.config.conexao_erp import ConfigurarConexaoErp
from app.application.config.portas import RepositorioLojas
from app.application.config.vendedores_erp import (
    ImportarVendedoresErp,
    LeitorVendedoresErp,
    LeitorVendedoresErpNaoConfigurado,
)
from app.application.estoque_erp import ErpNaoConfigurado, FonteEstoqueErp, SincronizarEstoqueErp
from app.application.followup import ConfigurarFollowup
from app.application.importacao.importar import ImportarPlanilha
from app.application.importacao.portas import GeradorModelo
from app.application.metricas import MetricasAgente
from app.application.midia import ArmazenamentoMidia, ReceberMidia
from app.application.painel.casos_de_uso import CasosPainel
from app.application.painel.pausar_ia import PausarIAProvisorio
from app.application.whatsapp import (
    PausarIA,
    ProcessarMensagemWhatsApp,
    RegistroEnviadas,
    WhatsAppGateway,
)
from app.infra.composicao import (
    criar_agendador,
    criar_canal_whatsapp,
    criar_gateway_whatsapp,
    montar_casos_config,
    montar_casos_painel,
    montar_sincronizar_estoque_erp,
)
from app.infra.mercadophone import MercadoPhoneNaoConfigurado, get_cliente_mercadophone
from app.infra.settings import Settings, get_settings


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
    return montar_casos_config(session)


def get_configurar_followup(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ConfigurarFollowup:
    return ConfigurarFollowup(RepositorioLojasSql(session), RepositorioConfigFollowupSql(session))


def get_metricas_agente(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> MetricasAgente:
    return MetricasAgente(RepositorioLojasSql(session), LeitorMetricasSql(session))


def get_configurar_conexao_erp(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ConfigurarConexaoErp:
    return ConfigurarConexaoErp(RepositorioLojasSql(session), RepositorioConexaoErpSql(session))


def get_leitor_vendedores_erp() -> LeitorVendedoresErp:
    """Leitor do Mercado Phone; sem `MERCADOPHONE_API_KEY` devolve um que falha com mensagem."""
    try:
        return LeitorVendedoresMercadoPhone(get_cliente_mercadophone())
    except MercadoPhoneNaoConfigurado:
        return LeitorVendedoresErpNaoConfigurado()


def get_importar_vendedores_erp(
    session: Annotated[AsyncSession, Depends(get_session)],
    leitor: Annotated[LeitorVendedoresErp, Depends(get_leitor_vendedores_erp)],
) -> ImportarVendedoresErp:
    return ImportarVendedoresErp(
        RepositorioLojasSql(session),
        RepositorioConexaoErpSql(session),
        RepositorioVendedoresSql(session),
        leitor,
    )


def get_importador(session: Annotated[AsyncSession, Depends(get_session)]) -> ImportarPlanilha:
    """Importador na sessao da requisicao: uma transacao, commit so apos validar e gravar tudo."""
    return ImportarPlanilha(
        montar_casos_config(session),
        LeitorXlsx(),
        commit=session.commit,
        rollback=session.rollback,
    )


@lru_cache
def _redis() -> Redis:
    return cast(Redis, Redis.from_url(get_settings().redis_url))


def get_barramento() -> BarramentoMensagens:
    """Barramento de mensagens (Redis pub/sub a partir de `REDIS_URL`), entre processos."""
    return BarramentoRedis(_redis())


def get_lojas(session: Annotated[AsyncSession, Depends(get_session)]) -> RepositorioLojas:
    return RepositorioLojasSql(session)


@lru_cache
def _redis_arq() -> ArqRedis:
    return cast(ArqRedis, ArqRedis.from_url(get_settings().redis_url))


def get_agendar() -> Callable[[UUID], Awaitable[None]]:
    """`agendar(conversa_id)` da fila arq (mesmo prefixo e janela do worker); so enfileira."""
    return criar_agendador(_redis_arq()).agendar


def get_receber_mensagem(
    session: Annotated[AsyncSession, Depends(get_session)],
    agendar: Annotated[Callable[[UUID], Awaitable[None]], Depends(get_agendar)],
    barramento: Annotated[BarramentoMensagens, Depends(get_barramento)],
) -> ReceberMensagem:
    return ReceberMensagem(
        RepositorioConversasSql(session), agendar, painel=PublicadorPainelBarramento(barramento)
    )


def get_armazenamento_midia() -> ArmazenamentoMidia:
    return ArmazenamentoMidiaDisco(get_settings().midia_dir)


@lru_cache
def _gateway_whatsapp() -> EvolutionGateway:
    return criar_gateway_whatsapp(get_settings())


def get_whatsapp_gateway() -> WhatsAppGateway:
    """Cliente da Evolution (um por processo: reaproveita as conexoes HTTP)."""
    return _gateway_whatsapp()


def get_registro_enviadas() -> RegistroEnviadas:
    return RegistroEnviadasRedis(_redis())


def get_canal_whatsapp(
    gateway: Annotated[WhatsAppGateway, Depends(get_whatsapp_gateway)],
    registro: Annotated[RegistroEnviadas, Depends(get_registro_enviadas)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> EvolutionAdapter:
    return criar_canal_whatsapp(gateway, registro, settings)


def get_casos_painel(
    session: Annotated[AsyncSession, Depends(get_session)],
    barramento: Annotated[BarramentoMensagens, Depends(get_barramento)],
    whatsapp: Annotated[EvolutionAdapter, Depends(get_canal_whatsapp)],
) -> CasosPainel:
    return montar_casos_painel(session, barramento, whatsapp=whatsapp)


def get_pausar_ia(
    session: Annotated[AsyncSession, Depends(get_session)],
    barramento: Annotated[BarramentoMensagens, Depends(get_barramento)],
) -> PausarIA:
    """Pausa provisoria (dono = vendedor + DonoMudou); sera religada ao handoff (#32)."""
    return PausarIAProvisorio(RepositorioPainelSql(session), PublicadorPainelBarramento(barramento))


def get_processar_whatsapp(
    session: Annotated[AsyncSession, Depends(get_session)],
    agendar: Annotated[Callable[[UUID], Awaitable[None]], Depends(get_agendar)],
    barramento: Annotated[BarramentoMensagens, Depends(get_barramento)],
    gateway: Annotated[WhatsAppGateway, Depends(get_whatsapp_gateway)],
    registro: Annotated[RegistroEnviadas, Depends(get_registro_enviadas)],
    armazenamento: Annotated[ArmazenamentoMidia, Depends(get_armazenamento_midia)],
    pausar: Annotated[PausarIA, Depends(get_pausar_ia)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> ProcessarMensagemWhatsApp:
    painel = PublicadorPainelBarramento(barramento)
    conversas = RepositorioConversasSql(session)
    base = settings.api_publica_url.rstrip("/")
    return ProcessarMensagemWhatsApp(
        receber=ReceberMensagem(conversas, agendar, painel=painel),
        mensagens_do_celular=conversas,
        nomes=conversas,
        gateway=gateway,
        receber_midia=ReceberMidia(armazenamento, settings.midia_max_bytes),
        url_midia=lambda nome: f"{base}/midias/{nome}",
        registro=registro,
        pausar=pausar,
        repo_conversas=conversas,
        painel=painel,
        graca_eco_s=settings.whatsapp_eco_graca_s,
    )


def get_gerador_modelo() -> GeradorModelo:
    return GeradorModeloXlsx()


def get_receber_midia() -> ReceberMidia:
    return ReceberMidia(get_armazenamento_midia(), get_settings().midia_max_bytes)


def get_fonte_estoque_erp() -> FonteEstoqueErp:
    """Fonte de estoque do ERP; sem `MERCADOPHONE_API_KEY` no servidor, fica desligada."""
    try:
        return FonteEstoqueMercadoPhone(get_cliente_mercadophone())
    except MercadoPhoneNaoConfigurado as exc:
        raise ErpNaoConfigurado(str(exc)) from exc


def get_sincronizar_estoque_erp(
    session: Annotated[AsyncSession, Depends(get_session)],
    fonte: Annotated[FonteEstoqueErp, Depends(get_fonte_estoque_erp)],
) -> SincronizarEstoqueErp:
    return montar_sincronizar_estoque_erp(session, fonte)


# --- autenticacao ---------------------------------------------------------------------------

COOKIE_SESSAO = "sessao"


def get_repositorio_usuarios(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> RepositorioUsuarios:
    return RepositorioUsuariosSql(session)


def get_hasher_senha() -> HasherSenha:
    return HasherSenhaArgon2()


def get_sessoes(settings: Annotated[Settings, Depends(get_settings)]) -> Sessoes:
    return SessoesRedis(_redis(), ttl_s=settings.sessao_ttl_horas * 3600)


async def sessao_atual(
    sessoes: Annotated[Sessoes, Depends(get_sessoes)],
    sessao: Annotated[str | None, Cookie()] = None,
) -> SessaoAtual:
    """Le o cookie de sessao, renova o TTL e devolve quem esta logado; sem sessao valida, 401."""
    if not sessao:
        raise SessaoInvalida
    dados = await sessoes.obter(sessao)
    if dados is None:
        raise SessaoInvalida
    await sessoes.renovar(sessao)
    return SessaoAtual(usuario_id=dados.usuario_id, loja_id=dados.loja_id, token=sessao)
