"""Schemas Pydantic da API do painel (alimentam o OpenAPI e o cliente TypeScript).

Dinheiro trafega como Decimal (JSON: string `"5339.40"`), como no resto da API.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, StringConstraints

from app.application.handoff import AcordoFechado, ResumoHandoff
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
    dono: str = Field(
        description=(
            "`ia`, `vendedor:<id do vendedor>` ou `vendedor` (aguardando vendedor: "
            "a IA chamou um vendedor e ninguem assumiu ainda)."
        )
    )
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
    transcricao: str | None
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
            transcricao=m.transcricao,
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


class AcordoFechadoSchema(BaseModel):
    """Acordo que a IA fechou com o cliente antes de chamar o vendedor."""

    fechado_em: datetime
    forma: str | None = Field(description="Forma escolhida na proposta (ex.: crédito em 12x).")
    valor_total: Decimal | None = None
    data_prevista: date | None = Field(description="Quando o cliente vai à loja.")
    endereco: str | None = Field(description="Endereço que a IA informou ao cliente.")
    horarios: str | None = Field(description="Horários que a IA informou ao cliente.")
    pix_chave: str | None = Field(description="Chave Pix informada (só no Pix); null sem chave.")
    pix_favorecido: str | None = None

    @classmethod
    def de(cls, a: AcordoFechado) -> AcordoFechadoSchema:
        return cls(
            fechado_em=a.fechado_em,
            forma=a.forma,
            valor_total=a.valor_total,
            data_prevista=a.data_prevista,
            endereco=a.endereco,
            horarios=a.horarios,
            pix_chave=a.pix_chave,
            pix_favorecido=a.pix_favorecido,
        )


class ResumoHandoffSchema(BaseModel):
    """Resumo para o vendedor: campos estruturados (deterministicos) + observacoes do LLM."""

    motivo: str
    aparelho_desejado: str | None
    troca: str | None
    valor_troca: Decimal | None
    proposta: str | None
    valor_proposta: Decimal | None
    forma_pagamento: str | None
    data_prevista: date | None
    pendencias: list[str]
    observacoes: str | None = Field(description="2 a 3 frases do LLM; null se ele falhou.")
    gerado_em: datetime
    cor: str | None = None
    sku: str | None = None
    troca_condicao: str | None = Field(
        default=None, description="Estado do usado em poucas palavras (tela, bateria...)."
    )
    troca_status: str | None = Field(
        default=None, description="avaliada, avaliacao_na_loja ou sem_troca (ultima proposta)."
    )
    valor_aparelho: Decimal | None = None
    desconto: Decimal | None = None
    parcelas: int | None = None
    valor_parcela: Decimal | None = None
    ultimas_mensagens_cliente: list[str] = Field(
        default_factory=list, description="Ultimas falas do cliente (truncadas)."
    )
    acordo: AcordoFechadoSchema | None = Field(
        default=None, description="Acordo fechado pela IA antes do handoff; null se não houve."
    )

    @classmethod
    def de(cls, r: ResumoHandoff) -> ResumoHandoffSchema:
        return cls(
            motivo=r.motivo,
            aparelho_desejado=r.aparelho_desejado,
            troca=r.troca,
            valor_troca=r.valor_troca,
            proposta=r.proposta,
            valor_proposta=r.valor_proposta,
            forma_pagamento=r.forma_pagamento,
            data_prevista=r.data_prevista,
            pendencias=r.pendencias,
            observacoes=r.observacoes,
            gerado_em=r.gerado_em,
            cor=r.cor,
            sku=r.sku,
            troca_condicao=r.troca_condicao,
            troca_status=r.troca_status,
            valor_aparelho=r.valor_aparelho,
            desconto=r.desconto,
            parcelas=r.parcelas,
            valor_parcela=r.valor_parcela,
            ultimas_mensagens_cliente=list(r.ultimas_mensagens_cliente),
            acordo=None if r.acordo is None else AcordoFechadoSchema.de(r.acordo),
        )


class DetalheLeadSchema(BaseModel):
    card: CardLeadSchema
    ficha: dict[str, Any] = Field(description="Ficha de qualificacao (JSON do dominio).")
    pendencias: list[str] = Field(description="Codigos do que falta para liberar o preco.")
    mensagens: list[MensagemSchema]
    eventos: list[EventoLeadSchema]
    proposta: dict[str, Any] | None
    handoff_solicitado: bool
    motivo_handoff: str | None
    resumo_handoff: ResumoHandoffSchema | None = Field(
        description="Resumo gerado quando a IA chamou o vendedor; null caso contrario."
    )

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
            resumo_handoff=(
                None if d.resumo_handoff is None else ResumoHandoffSchema.de(d.resumo_handoff)
            ),
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
