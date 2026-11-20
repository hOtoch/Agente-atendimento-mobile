"""WhatsApp (Evolution API): portas e caso de uso do webhook de entrada.

O adaptador de entrada so normaliza o payload em `EventoMensagemWhatsApp`; quem decide o que
fazer com ele (cliente falou, vendedor digitou no celular, eco da propria API) e
`ProcessarMensagemWhatsApp`, que reaproveita `ReceberMensagem` do chat web.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from app.application.canal import (
    Canal,
    MensagemEntrada,
    ReceberMensagem,
    RepositorioConversas,
    TipoMensagem,
)
from app.application.midia import MidiaGrandeDemais, ReceberMidia, TipoMidiaNaoSuportado
from app.application.painel.eventos import EventoMensagemNova
from app.application.painel.publicador import (
    PublicadorPainel,
    PublicadorPainelNulo,
    publicar_sem_falhar,
)

log = logging.getLogger(__name__)

PREFIXO_INSTANCIA = "loja-"


def nome_instancia(loja_id: UUID) -> str:
    """Nome da instancia da Evolution de uma loja (deterministico: nada para persistir)."""
    return f"{PREFIXO_INSTANCIA}{loja_id}"


def loja_da_instancia(nome: str) -> UUID | None:
    """Inverso de `nome_instancia`; None se o nome nao for de uma instancia nossa."""
    if not nome.startswith(PREFIXO_INSTANCIA):
        return None
    try:
        loja_id = UUID(nome[len(PREFIXO_INSTANCIA) :])
    except ValueError:
        return None
    return loja_id if nome_instancia(loja_id) == nome else None


def id_externo_whatsapp(loja_id: UUID, id_whatsapp: str) -> str:
    """Chave de idempotencia em `mensagens.id_externo` (unica por canal)."""
    return f"{loja_id}:{id_whatsapp}"


class EstadoConexao(StrEnum):
    CONECTADO = "conectado"
    CONECTANDO = "conectando"
    DESCONECTADO = "desconectado"
    INEXISTENTE = "inexistente"
    """A loja ainda nao tem instancia na Evolution."""


@dataclass(frozen=True, slots=True)
class QrWhatsApp:
    qr_base64: str | None
    """Imagem do QR (`data:image/png;base64,...`); None se ja conectado ou ainda sem QR."""
    status: EstadoConexao


@dataclass(frozen=True, slots=True)
class MidiaBaixada:
    dados: bytes
    tipo_mime: str


class ErroGateway(Exception):
    """Falha ao falar com a Evolution (rede, HTTP != 2xx ou resposta inesperada)."""

    def __init__(self, mensagem: str, status: int | None = None) -> None:
        super().__init__(mensagem)
        self.status = status


class WhatsAppGateway(Protocol):
    """Cliente da API da Evolution. `numero` e so digitos (DDI+DDD+numero).

    Os `enviar_*` devolvem o id da mensagem no WhatsApp (None se a resposta nao trouxer),
    usado para ignorar o eco `fromMe`. `audio`/`imagem` aceitam URL ou base64.
    """

    async def criar_instancia(self, loja_id: UUID) -> None:
        """Idempotente: cria a instancia da loja e aponta o webhook dela para a nossa API."""
        ...

    async def obter_qr(self, loja_id: UUID) -> QrWhatsApp: ...

    async def status_conexao(self, loja_id: UUID) -> EstadoConexao: ...

    async def enviar_texto(self, loja_id: UUID, numero: str, texto: str) -> str | None: ...

    async def enviar_audio(self, loja_id: UUID, numero: str, audio: str) -> str | None: ...

    async def enviar_imagem(
        self,
        loja_id: UUID,
        numero: str,
        imagem: str,
        legenda: str | None = None,
        tipo_mime: str = "image/jpeg",
    ) -> str | None: ...

    async def digitando(self, loja_id: UUID, numero: str, duracao_ms: int = 1500) -> None: ...

    async def baixar_midia(self, loja_id: UUID, id_mensagem: str) -> MidiaBaixada: ...


class RegistroEnviadas(Protocol):
    """Ids de mensagens que a PROPRIA API enviou: o eco `fromMe` delas nao e o vendedor."""

    async def registrar(self, loja_id: UUID, id_whatsapp: str) -> None: ...

    async def foi_enviada(self, loja_id: UUID, id_whatsapp: str) -> bool: ...


class PausarIA(Protocol):
    """O vendedor falou direto no celular da loja: a IA para de responder esse lead."""

    async def pausar_por_vendedor(self, loja_id: UUID, lead_id: UUID) -> None: ...


class RepositorioMensagensDoCelular(Protocol):
    async def registrar_saida_vendedor(
        self,
        conversa_id: UUID,
        *,
        loja_id: UUID,
        canal: Canal,
        id_externo: str,
        tipo: TipoMensagem,
        texto: str | None,
        midia_url: str | None,
    ) -> bool:
        """Grava `autor=vendedor`, `direcao=saida`. Idempotente: False se ja existia."""
        ...


class NomesDeContatos(Protocol):
    async def definir_nome_se_vazio(
        self, loja_id: UUID, canal: Canal, contato: str, nome: str
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class EventoMensagemWhatsApp:
    """Mensagem do webhook ja normalizada (a midia ainda nao foi baixada)."""

    loja_id: UUID
    id_whatsapp: str
    de_mim: bool
    """`fromMe`: digitada pelo celular da loja (ou eco de algo que a API enviou)."""
    contato: str
    """Telefone do cliente (so digitos)."""
    nome: str | None
    tipo: TipoMensagem
    texto: str | None
    tipo_mime: str | None
    baixar_midia: bool
    recebida_em: datetime


class ResultadoWebhook(StrEnum):
    PROCESSADA = "processada"
    DUPLICADA = "duplicada"
    ECO = "eco"
    IGNORADA = "ignorada"


class ProcessarMensagemWhatsApp:
    def __init__(
        self,
        *,
        receber: ReceberMensagem,
        mensagens_do_celular: RepositorioMensagensDoCelular,
        nomes: NomesDeContatos,
        gateway: WhatsAppGateway,
        receber_midia: ReceberMidia,
        url_midia: Callable[[str], str],
        registro: RegistroEnviadas,
        pausar: PausarIA,
        repo_conversas: RepositorioConversas,
        painel: PublicadorPainel | None = None,
        graca_eco_s: float = 0.5,
    ) -> None:
        self._receber = receber
        self._celular = mensagens_do_celular
        self._nomes = nomes
        self._gateway = gateway
        self._receber_midia = receber_midia
        self._url_midia = url_midia
        self._registro = registro
        self._pausar = pausar
        self._conversas = repo_conversas
        self._painel = painel or PublicadorPainelNulo()
        self._graca_eco_s = graca_eco_s

    async def __call__(self, evento: EventoMensagemWhatsApp) -> ResultadoWebhook:
        if evento.de_mim:
            return await self._do_celular(evento)
        return await self._do_cliente(evento)

    async def _do_cliente(self, evento: EventoMensagemWhatsApp) -> ResultadoWebhook:
        midia_url = await self._guardar_midia(evento)
        _, nova = await self._receber(
            MensagemEntrada(
                loja_id=evento.loja_id,
                canal=Canal.WHATSAPP,
                id_externo=id_externo_whatsapp(evento.loja_id, evento.id_whatsapp),
                remetente=evento.contato,
                tipo=evento.tipo,
                texto=evento.texto,
                midia_url=midia_url,
                recebida_em=evento.recebida_em,
            )
        )
        if evento.nome:
            await self._nomes.definir_nome_se_vazio(
                evento.loja_id, Canal.WHATSAPP, evento.contato, evento.nome
            )
        return ResultadoWebhook.PROCESSADA if nova else ResultadoWebhook.DUPLICADA

    async def _do_celular(self, evento: EventoMensagemWhatsApp) -> ResultadoWebhook:
        if await self._e_eco(evento):
            return ResultadoWebhook.ECO
        midia_url = await self._guardar_midia(evento)
        lead_id, conversa_id = await self._conversas.obter_ou_criar(
            evento.loja_id, Canal.WHATSAPP, evento.contato
        )
        nova = await self._celular.registrar_saida_vendedor(
            conversa_id,
            loja_id=evento.loja_id,
            canal=Canal.WHATSAPP,
            id_externo=id_externo_whatsapp(evento.loja_id, evento.id_whatsapp),
            tipo=evento.tipo,
            texto=evento.texto,
            midia_url=midia_url,
        )
        if not nova:
            return ResultadoWebhook.DUPLICADA
        await publicar_sem_falhar(
            self._painel,
            evento.loja_id,
            EventoMensagemNova(
                lead_id=lead_id,
                conversa_id=conversa_id,
                autor="vendedor",
                direcao="saida",
                tipo=evento.tipo.value,
                texto=evento.texto,
                midia_url=midia_url,
                em=evento.recebida_em,
            ),
        )
        await self._pausar.pausar_por_vendedor(evento.loja_id, lead_id)
        return ResultadoWebhook.PROCESSADA

    async def _e_eco(self, evento: EventoMensagemWhatsApp) -> bool:
        if await self._registro.foi_enviada(evento.loja_id, evento.id_whatsapp):
            return True
        if self._graca_eco_s <= 0:
            return False
        # O webhook pode chegar antes de o envio devolver o id: espera um instante e repete.
        await asyncio.sleep(self._graca_eco_s)
        return await self._registro.foi_enviada(evento.loja_id, evento.id_whatsapp)

    async def _guardar_midia(self, evento: EventoMensagemWhatsApp) -> str | None:
        """Baixa e guarda a midia; falhar aqui nao pode perder a mensagem."""
        if not evento.baixar_midia:
            return None
        try:
            midia = await self._gateway.baixar_midia(evento.loja_id, evento.id_whatsapp)
            nome = await self._receber_midia(midia.dados, midia.tipo_mime)
        except (ErroGateway, TipoMidiaNaoSuportado, MidiaGrandeDemais):
            log.warning(
                "midia %s da loja %s nao foi guardada", evento.id_whatsapp, evento.loja_id,
                exc_info=True,
            )  # fmt: skip
            return None
        return self._url_midia(nome)


class ConectarWhatsApp:
    """Onboarding: devolve o QR para a loja conectar o numero (cria a instancia se preciso)."""

    def __init__(self, gateway: WhatsAppGateway) -> None:
        self._gateway = gateway

    async def __call__(self, loja_id: UUID) -> QrWhatsApp:
        if await self._gateway.status_conexao(loja_id) is EstadoConexao.CONECTADO:
            return QrWhatsApp(qr_base64=None, status=EstadoConexao.CONECTADO)
        # Idempotente: tambem reaplica o webhook se a instancia ja existir.
        await self._gateway.criar_instancia(loja_id)
        return await self._gateway.obter_qr(loja_id)
