"""Schemas Pydantic da API do painel (alimentam o OpenAPI e o cliente TypeScript).

Dinheiro trafega como Decimal (JSON: string `"5339.40"`), como no resto da API.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, StringConstraints

from app.application.painel.casos_de_uso import (
    CardLead,
    ColunaKanban,
    DetalheLead,
    EnvioMensagem,
)
from app.application.painel.portas import EventoRegistro, MensagemRegistro
from app.domain.kanban import Etapa

CanalLiteral = Literal["webchat", "whatsapp", "instagram"]
AutorLiteral = Literal["cliente", "ia", "vendedor"]
TextoNaoVazio = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)
]


class ErroCampoSchema(BaseModel):
    caminho: str
    mensagem: str


class ErrosSchema(BaseModel):
    """Corpo uniforme de 404, 409 e 422."""

    erros: list[ErroCampoSchema]


class CardLeadSchema(BaseModel):
    id: UUID
    nome: str | None
    telefone: str
    canal: CanalLiteral
    etapa: Etapa
    etapa_desde: datetime
    dono: str = Field(description="`ia` ou `vendedor:<id do vendedor>`.")
    vendedor_id: UUID | None
    vendedor_nome: str | None
    aparelho_desejado: str | None
    valor_estimado: Decimal | None
    criado_em: datetime

    @classmethod
    def de(cls, c: CardLead) -> CardLeadSchema:
        return cls(
            id=c.id,
            nome=c.nome,
            telefone=c.telefone,
            canal=c.canal.value,
            etapa=c.etapa,
            etapa_desde=c.etapa_desde,
            dono=c.dono,
            vendedor_id=c.vendedor_id,
            vendedor_nome=c.vendedor_nome,
            aparelho_desejado=c.aparelho_desejado,
            valor_estimado=c.valor_estimado,
            criado_em=c.criado_em,
        )


class ColunaKanbanSchema(BaseModel):
    etapa: Etapa
    nome: str
    leads: list[CardLeadSchema]


class KanbanSchema(BaseModel):
    etapas: list[ColunaKanbanSchema]

    @classmethod
    def de(cls, colunas: list[ColunaKanban]) -> KanbanSchema:
        return cls(
            etapas=[
                ColunaKanbanSchema(
                    etapa=c.etapa, nome=c.nome, leads=[CardLeadSchema.de(x) for x in c.leads]
                )
                for c in colunas
            ]
        )


class MensagemSchema(BaseModel):
    id: UUID
    conversa_id: UUID
    direcao: Literal["entrada", "saida"]
    autor: AutorLiteral
    tipo: Literal["texto", "audio", "imagem"]
    texto: str | None
    midia_url: str | None
    criada_em: datetime

    @classmethod
    def de(cls, m: MensagemRegistro) -> MensagemSchema:
        return cls(
            id=m.id,
            conversa_id=m.conversa_id,
            direcao=m.direcao,
            autor=m.autor,
            tipo=m.tipo.value,
            texto=m.texto,
            midia_url=m.midia_url,
            criada_em=m.criada_em,
        )


class EventoLeadSchema(BaseModel):
    id: UUID
    tipo: str
    payload: dict[str, Any]
    criado_em: datetime

    @classmethod
    def de(cls, e: EventoRegistro) -> EventoLeadSchema:
        return cls(id=e.id, tipo=e.tipo, payload=e.payload, criado_em=e.criado_em)


class DetalheLeadSchema(BaseModel):
    card: CardLeadSchema
    ficha: dict[str, Any] = Field(description="Ficha de qualificacao (JSON do dominio).")
    pendencias: list[str] = Field(description="Codigos do que falta para liberar o preco.")
    mensagens: list[MensagemSchema]
    eventos: list[EventoLeadSchema]
    proposta: dict[str, Any] | None
    handoff_solicitado: bool
    motivo_handoff: str | None

    @classmethod
    def de(cls, d: DetalheLead) -> DetalheLeadSchema:
        return cls(
            card=CardLeadSchema.de(d.card),
            ficha=d.ficha,
            pendencias=d.pendencias,
            mensagens=[MensagemSchema.de(m) for m in d.mensagens],
            eventos=[EventoLeadSchema.de(e) for e in d.eventos],
            proposta=d.proposta,
            handoff_solicitado=d.handoff_solicitado,
            motivo_handoff=d.motivo_handoff,
        )


class MoverEtapaIn(BaseModel):
    etapa: Etapa


class AssumirIn(BaseModel):
    vendedor_id: UUID


class MensagemVendedorIn(BaseModel):
    texto: TextoNaoVazio


class EnvioMensagemSchema(BaseModel):
    mensagem: MensagemSchema
    enviada: bool = Field(
        description="False quando o canal do lead ainda nao tem adaptador de envio."
    )

    @classmethod
    def de(cls, e: EnvioMensagem) -> EnvioMensagemSchema:
        return cls(mensagem=MensagemSchema.de(e.mensagem), enviada=e.enviada)


# --- eventos do SSE (documentados no OpenAPI para o cliente TS tipar a uniao) -----------------


class EventoEtapaMudouSchema(BaseModel):
    evento: Literal["EtapaMudou"]
    lead_id: UUID
    de: Etapa
    para: Etapa
    ator: Literal["ia", "vendedor", "sistema"]
    motivo: str
    em: datetime


class EventoMensagemNovaSchema(BaseModel):
    evento: Literal["MensagemNova"]
    lead_id: UUID
    conversa_id: UUID
    autor: AutorLiteral
    direcao: Literal["entrada", "saida"]
    tipo: Literal["texto", "audio", "imagem"]
    texto: str | None
    midia_url: str | None
    em: datetime


class EventoDonoMudouSchema(BaseModel):
    evento: Literal["DonoMudou"]
    lead_id: UUID
    dono: str
    vendedor_id: UUID | None
    em: datetime


EventoPainelSchema = Annotated[
    EventoEtapaMudouSchema | EventoMensagemNovaSchema | EventoDonoMudouSchema,
    Field(discriminator="evento"),
]
