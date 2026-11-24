"""Casos de uso do painel. O dominio (`kanban`) decide se um movimento e valido."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from app.application.agente.estado import EstadoAtendimento, aparelho_desejado
from app.application.canal import Canal, CanalPort, MensagemSaida, TipoMensagem
from app.application.handoff import (
    CasosHandoff,
    ConflitoDono,
    LeadNaoEncontrado,
    ResumoHandoff,
)
from app.application.painel.eventos import EventoEtapaMudou, EventoLeadRemovido, EventoMensagemNova
from app.application.painel.portas import (
    DONO_IA,
    DONO_VENDEDOR,
    EventoRegistro,
    LeadRegistro,
    MensagemRegistro,
    RepositorioPainel,
)
from app.application.painel.publicador import PublicadorPainel, publicar_sem_falhar
from app.domain.ficha import pendencias
from app.domain.kanban import Ator, Etapa, MovimentoInvalido, mover_manual_com_evento


class MovimentoEtapaInvalido(Exception):
    """O kanban recusou o movimento manual (regra do dominio)."""

    def __init__(self, motivo: str) -> None:
        super().__init__(motivo)
        self.motivo = motivo


@dataclass(frozen=True, slots=True)
class CardLead:
    """O que o card do kanban precisa."""

    id: UUID
    nome: str | None
    telefone: str
    canal: Canal
    etapa: Etapa
    etapa_desde: datetime
    dono: str
    """`ia` ou `vendedor:<id>`."""
    vendedor_id: UUID | None
    vendedor_nome: str | None
    aparelho_desejado: str | None
    valor_estimado: Decimal | None
    criado_em: datetime


@dataclass(frozen=True, slots=True)
class ColunaKanban:
    etapa: Etapa
    leads: list[CardLead]

    @property
    def nome(self) -> str:
        return self.etapa.nome_exibicao


@dataclass(frozen=True, slots=True)
class DetalheLead:
    card: CardLead
    ficha: dict[str, Any]
    pendencias: list[str]
    mensagens: list[MensagemRegistro]
    eventos: list[EventoRegistro]
    proposta: dict[str, Any] | None
    handoff_solicitado: bool
    motivo_handoff: str | None
    resumo_handoff: ResumoHandoff | None
    """Resumo gravado quando a IA chamou o vendedor; None se o handoff nao veio dela."""


@dataclass(frozen=True, slots=True)
class EnvioMensagem:
    mensagem: MensagemRegistro
    enviada: bool
    """False quando o canal do lead ainda nao tem adaptador (a mensagem so foi registrada)."""


def _decimal(valor: object) -> Decimal | None:
    try:
        return Decimal(str(valor)) if valor is not None else None
    except InvalidOperation:
        return None


def valor_estimado(estado: EstadoAtendimento) -> Decimal | None:
    """Total da ultima proposta (a vista ou pago); sem forma escolhida, o preco do aparelho."""
    proposta = estado.ultima_proposta
    if not proposta:
        return None
    forma = proposta.get("forma_escolhida") or {}
    for chave in ("total_pago", "valor_a_vista"):
        valor = _decimal(forma.get(chave))
        if valor is not None:
            return valor
    return _decimal(proposta.get("preco_aparelho"))


def dono_exibicao(lead: LeadRegistro) -> str:
    if lead.dono == DONO_VENDEDOR:
        # sem vendedor_id: conversa aguardando vendedor (a IA ja calou)
        return DONO_VENDEDOR if lead.vendedor_id is None else f"{DONO_VENDEDOR}:{lead.vendedor_id}"
    return DONO_IA


def card_de(lead: LeadRegistro) -> CardLead:
    return CardLead(
        id=lead.id,
        nome=lead.nome,
        telefone=lead.telefone,
        canal=lead.canal,
        etapa=lead.etapa,
        etapa_desde=lead.etapa_desde,
        dono=dono_exibicao(lead),
        vendedor_id=lead.vendedor_id,
        vendedor_nome=lead.vendedor_nome,
        aparelho_desejado=aparelho_desejado(lead.estado),
        valor_estimado=valor_estimado(lead.estado),
        criado_em=lead.criado_em,
    )


def _agora() -> datetime:
    return datetime.now(UTC)


class CasosPainel:
    def __init__(
        self,
        *,
        repo: RepositorioPainel,
        publicador: PublicadorPainel,
        handoff: CasosHandoff,
        canais: Mapping[Canal, CanalPort],
        agora: Callable[[], datetime] = _agora,
    ) -> None:
        self._repo = repo
        self._publicador = publicador
        self._handoff = handoff
        self._canais = canais
        self._agora = agora

    async def _lead(self, loja_id: UUID, lead_id: UUID) -> LeadRegistro:
        lead = await self._repo.obter_lead(loja_id, lead_id)
        if lead is None:
            raise LeadNaoEncontrado(lead_id)
        return lead

    async def _card(self, loja_id: UUID, lead_id: UUID) -> CardLead:
        return card_de(await self._lead(loja_id, lead_id))

    async def kanban(self, loja_id: UUID) -> list[ColunaKanban]:
        """Sempre as cinco etapas, em ordem; em cada uma, quem esta ha mais tempo vem primeiro."""
        por_etapa: dict[Etapa, list[CardLead]] = {etapa: [] for etapa in Etapa}
        for lead in await self._repo.listar_leads(loja_id):
            por_etapa[lead.etapa].append(card_de(lead))
        return [
            ColunaKanban(etapa, sorted(cards, key=lambda c: c.etapa_desde))
            for etapa, cards in por_etapa.items()
        ]

    async def detalhe(self, loja_id: UUID, lead_id: UUID) -> DetalheLead:
        lead = await self._lead(loja_id, lead_id)
        estado = lead.estado
        return DetalheLead(
            card=card_de(lead),
            ficha=estado.ficha.para_dict(),
            pendencias=[p.name.lower() for p in pendencias(estado.ficha)],
            mensagens=await self._repo.listar_mensagens(loja_id, lead_id),
            eventos=await self._repo.listar_eventos(loja_id, lead_id),
            proposta=estado.ultima_proposta,
            handoff_solicitado=estado.handoff_solicitado,
            motivo_handoff=estado.motivo_handoff,
            resumo_handoff=(
                await self._handoff.resumo_do_lead(loja_id, lead_id)
                if estado.handoff_solicitado
                else None
            ),
        )

    async def mover_etapa(self, loja_id: UUID, lead_id: UUID, destino: Etapa) -> CardLead:
        lead = await self._lead(loja_id, lead_id)
        resultado = mover_manual_com_evento(lead.etapa, destino, Ator.VENDEDOR)
        if isinstance(resultado, MovimentoInvalido):
            raise MovimentoEtapaInvalido(resultado.motivo)
        _, mudou = resultado
        await self._repo.mover_etapa(
            loja_id,
            lead_id,
            mudou.para,
            {
                "de": mudou.de.value,
                "para": mudou.para.value,
                "ator": mudou.ator.value,
                "motivo": mudou.motivo,
            },
        )
        await publicar_sem_falhar(
            self._publicador,
            loja_id,
            EventoEtapaMudou(
                lead_id=lead_id,
                de=mudou.de,
                para=mudou.para,
                ator=mudou.ator.value,
                motivo=mudou.motivo,
                em=self._agora(),
            ),
        )
        return await self._card(loja_id, lead_id)

    async def resetar(self, loja_id: UUID, lead_id: UUID) -> None:
        """Apaga a conversa inteira: lead, mensagens e memoria da IA. Se o cliente escrever de
        novo, nasce um lead novo e a IA recomeca do zero."""
        if not await self._repo.apagar_lead(loja_id, lead_id):
            raise LeadNaoEncontrado(lead_id)
        await publicar_sem_falhar(
            self._publicador, loja_id, EventoLeadRemovido(lead_id=lead_id, em=self._agora())
        )

    async def assumir(self, loja_id: UUID, lead_id: UUID, vendedor_id: UUID) -> CardLead:
        """Troca o dono para o vendedor (regra em `CasosHandoff`)."""
        return card_de(await self._handoff.assumir(loja_id, lead_id, vendedor_id))

    async def devolver(self, loja_id: UUID, lead_id: UUID) -> CardLead:
        return card_de(await self._handoff.devolver(loja_id, lead_id))

    async def enviar_mensagem(self, loja_id: UUID, lead_id: UUID, texto: str) -> EnvioMensagem:
        """Mensagem do vendedor: entrega pelo canal (se houver adaptador), registra e publica."""
        lead = await self._lead(loja_id, lead_id)
        if lead.dono != DONO_VENDEDOR:
            raise ConflitoDono("Assuma a conversa antes de enviar mensagens como vendedor.")
        if lead.conversa_id is None:
            raise ConflitoDono("O lead ainda nao tem conversa.")
        texto = texto.strip()
        canal = self._canais.get(lead.canal)
        if canal is not None:
            await canal.enviar(
                MensagemSaida(
                    loja_id=loja_id,
                    canal=lead.canal,
                    destinatario=lead.telefone,
                    tipo=TipoMensagem.TEXTO,
                    texto=texto,
                    midia_url=None,
                )
            )
        mensagem = await self._repo.registrar_mensagem_vendedor(
            loja_id, lead.conversa_id, lead.canal, texto
        )
        await publicar_sem_falhar(
            self._publicador,
            loja_id,
            EventoMensagemNova(
                lead_id=lead_id,
                conversa_id=lead.conversa_id,
                autor=mensagem.autor,
                direcao=mensagem.direcao,
                tipo=mensagem.tipo.value,
                texto=mensagem.texto,
                midia_url=mensagem.midia_url,
                em=mensagem.criada_em,
            ),
        )
        return EnvioMensagem(mensagem=mensagem, enviada=canal is not None)
