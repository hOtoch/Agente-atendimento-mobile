"""Schemas Pydantic da API de configuracao (separados do dominio).

Dinheiro e percentuais trafegam como Decimal (JSON: string `"3100.00"`; a entrada aceita
numero ou string). Os campos sao tipados de forma frouxa de proposito: as regras de negocio
(e as mensagens por campo) ficam nos casos de uso.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, Field

Num = Annotated[Decimal, Field(allow_inf_nan=False)]


class LojaIn(BaseModel):
    nome: str


class LojaOut(BaseModel):
    id: UUID
    nome: str


class PerfilSchema(BaseModel):
    nome_exibicao: str
    tom_de_voz: str = ""
    endereco: str = ""
    horarios: dict[str, str] = Field(default_factory=dict)
    whatsapp_contato: str = ""
    responder_em_audio: bool = True


class PrecoSchema(BaseModel):
    max_parcelas: int
    repassa_taxa: bool
    desconto_pix_tipo: str
    desconto_pix_valor: Num | None = None
    aceita_entrada_mais_cartao: bool
    desconto_teto: Num
    desconto_degrau: Num
    oportunidade_ativa: bool
    oportunidade_dias_minimos: int
    oportunidade_valor: Num
    oportunidade_conta_no_teto: bool = False


class TaxaSchema(BaseModel):
    chave: int | str
    bandeira: str
    taxa_pct: Num | None = None
    """null = "igual" (usa a Mastercard)."""


class TaxasSchema(BaseModel):
    taxas: list[TaxaSchema]


class LinhaTrocaSchema(BaseModel):
    marca: str = "Apple"
    modelo: str
    capacidade_gb: int
    valor_sem_detalhes: Num
    desconto_tela: Num | None = None
    desconto_tela_sem: bool = False
    desconto_traseira: Num | None = None
    desconto_traseira_sem: bool = False
    desconto_carcaca: Num | None = None
    desconto_carcaca_sem: bool = False
    desconto_bateria: Num | None = None
    desconto_bateria_sem: bool = False
    limite_bateria_pct: int


class TrocaSchema(BaseModel):
    tabela_troca: list[LinhaTrocaSchema]


class LinhaEstoqueSchema(BaseModel):
    sku: str
    marca: str = "Apple"
    modelo: str
    capacidade_gb: int
    cor: str
    condicao: str
    preco_pix: Num
    quantidade: int
    bateria_pct: int | None = None


class EstoqueSchema(BaseModel):
    estoque: list[LinhaEstoqueSchema]


class LinhaMapeamentoSchema(BaseModel):
    sku_externo: str
    marca: str = "Apple"
    modelo: str
    capacidade_gb: int
    cor: str
    condicao: str


class MapeamentoSchema(BaseModel):
    mapeamento_sku: list[LinhaMapeamentoSchema]


class ItemChecklistSchema(BaseModel):
    chave: str
    rotulo_ptbr: str
    completo: bool
    detalhe: str


class ChecklistSchema(BaseModel):
    itens: list[ItemChecklistSchema]


class VendedorIn(BaseModel):
    id: UUID | None = None
    """Ausente = vendedor novo; com id = atualiza o existente da loja."""
    nome: str
    telefone: str | None = None
    peso_percentual: Num
    ativo: bool = True


class VendedoresIn(BaseModel):
    vendedores: list[VendedorIn]


class VendedorSchema(BaseModel):
    id: UUID
    nome: str
    telefone: str | None
    peso_percentual: Num
    ativo: bool
    codigo_erp: str | None = None
    """Id no ERP (Mercado Phone); ausente = vendedor criado a mao."""


class VendedoresSchema(BaseModel):
    vendedores: list[VendedorSchema]
