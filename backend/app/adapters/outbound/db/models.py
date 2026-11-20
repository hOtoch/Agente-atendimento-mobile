"""Modelos SQLAlchemy (multi-loja: `loja_id` em todas as tabelas de negocio)."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    pass


Base.metadata.naming_convention = NAMING_CONVENTION


def _pk() -> Mapped[uuid.UUID]:
    return mapped_column(Uuid, primary_key=True, default=uuid.uuid4)


def _agora() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


def _loja_fk() -> Mapped[uuid.UUID]:
    return mapped_column(Uuid, ForeignKey("lojas.id", ondelete="CASCADE"), nullable=False)


class Loja(Base):
    __tablename__ = "lojas"

    id: Mapped[uuid.UUID] = _pk()
    nome: Mapped[str] = mapped_column(String(200), nullable=False)
    criado_em: Mapped[datetime] = _agora()


class Vendedor(Base):
    __tablename__ = "vendedores"
    __table_args__ = (
        CheckConstraint("peso_percentual >= 0 AND peso_percentual <= 100", name="peso_valido"),
    )

    id: Mapped[uuid.UUID] = _pk()
    loja_id: Mapped[uuid.UUID] = _loja_fk()
    nome: Mapped[str] = mapped_column(String(200), nullable=False)
    telefone: Mapped[str | None] = mapped_column(String(32))
    peso_percentual: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, server_default=text("0")
    )
    ativo: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    criado_em: Mapped[datetime] = _agora()


class Lead(Base):
    __tablename__ = "leads"
    __table_args__ = (
        UniqueConstraint("loja_id", "canal", "telefone", name="contato"),
        CheckConstraint("dono IN ('ia', 'vendedor')", name="dono_valido"),
        Index("ix_leads_loja_id_etapa", "loja_id", "etapa"),
    )

    id: Mapped[uuid.UUID] = _pk()
    loja_id: Mapped[uuid.UUID] = _loja_fk()
    nome: Mapped[str | None] = mapped_column(String(200))
    telefone: Mapped[str] = mapped_column(String(32), nullable=False)
    canal: Mapped[str] = mapped_column(String(32), nullable=False)
    etapa: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'novo_contato'")
    )
    dono: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'ia'"))
    vendedor_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("vendedores.id", ondelete="SET NULL")
    )
    criado_em: Mapped[datetime] = _agora()
    atualizado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class Conversa(Base):
    __tablename__ = "conversas"

    id: Mapped[uuid.UUID] = _pk()
    loja_id: Mapped[uuid.UUID] = _loja_fk()
    lead_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("leads.id", ondelete="CASCADE"), nullable=False, index=True
    )
    canal: Mapped[str] = mapped_column(String(32), nullable=False)
    criado_em: Mapped[datetime] = _agora()


class Mensagem(Base):
    __tablename__ = "mensagens"
    __table_args__ = (
        # Idempotencia: o mesmo (canal, id_externo) nunca entra duas vezes (NULLs nao colidem).
        UniqueConstraint("canal", "id_externo", name="canal_id_externo"),
        CheckConstraint("direcao IN ('entrada', 'saida')", name="direcao_valida"),
        CheckConstraint("autor IN ('cliente', 'ia', 'vendedor')", name="autor_valido"),
        CheckConstraint("tipo IN ('texto', 'audio', 'imagem')", name="tipo_valido"),
        Index("ix_mensagens_conversa_id_criado_em", "conversa_id", "criado_em"),
    )

    id: Mapped[uuid.UUID] = _pk()
    loja_id: Mapped[uuid.UUID] = _loja_fk()
    conversa_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("conversas.id", ondelete="CASCADE"), nullable=False
    )
    canal: Mapped[str] = mapped_column(String(32), nullable=False)
    direcao: Mapped[str] = mapped_column(String(16), nullable=False)
    autor: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'cliente'"))
    tipo: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'texto'"))
    conteudo: Mapped[str | None] = mapped_column(Text)
    midia_url: Mapped[str | None] = mapped_column(Text)
    id_externo: Mapped[str | None] = mapped_column(String(255))
    criado_em: Mapped[datetime] = _agora()


class Ficha(Base):
    __tablename__ = "fichas"
    __table_args__ = (UniqueConstraint("lead_id", "versao", name="lead_versao"),)

    id: Mapped[uuid.UUID] = _pk()
    loja_id: Mapped[uuid.UUID] = _loja_fk()
    lead_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("leads.id", ondelete="CASCADE"), nullable=False
    )
    versao: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    dados: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    criado_em: Mapped[datetime] = _agora()


class Evento(Base):
    __tablename__ = "eventos"
    __table_args__ = (Index("ix_eventos_loja_id_criado_em", "loja_id", "criado_em"),)

    id: Mapped[uuid.UUID] = _pk()
    loja_id: Mapped[uuid.UUID] = _loja_fk()
    lead_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("leads.id", ondelete="SET NULL")
    )
    tipo: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    criado_em: Mapped[datetime] = _agora()


def _sem_ck(campo: str) -> CheckConstraint:
    """SEM e NULL andam juntos: `sem` => valor NULL; senao o valor e obrigatorio."""
    return CheckConstraint(
        f"(desconto_{campo}_sem AND desconto_{campo} IS NULL) "
        f"OR (NOT desconto_{campo}_sem AND desconto_{campo} IS NOT NULL)",
        name=f"desconto_{campo}_sem_ou_valor",
    )


class PerfilLojaRow(Base):
    __tablename__ = "perfil_loja"

    loja_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("lojas.id", ondelete="CASCADE"), primary_key=True
    )
    nome_exibicao: Mapped[str] = mapped_column(String(200), nullable=False)
    tom_de_voz: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    endereco: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    horarios: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    whatsapp_contato: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("''")
    )


class RegrasPrecoRow(Base):
    __tablename__ = "regras_preco"
    __table_args__ = (
        CheckConstraint("max_parcelas >= 1 AND max_parcelas <= 21", name="max_parcelas_valido"),
        CheckConstraint(
            "desconto_pix_tipo IN ('nenhum', 'percentual', 'valor')",
            name="desconto_pix_tipo_valido",
        ),
    )

    loja_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("lojas.id", ondelete="CASCADE"), primary_key=True
    )
    max_parcelas: Mapped[int] = mapped_column(Integer, nullable=False)
    repassa_taxa: Mapped[bool] = mapped_column(Boolean, nullable=False)
    desconto_pix_tipo: Mapped[str] = mapped_column(String(16), nullable=False)
    desconto_pix_valor: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    aceita_entrada_mais_cartao: Mapped[bool] = mapped_column(Boolean, nullable=False)
    desconto_teto: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    desconto_degrau: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    oportunidade_ativa: Mapped[bool] = mapped_column(Boolean, nullable=False)
    oportunidade_dias_minimos: Mapped[int] = mapped_column(Integer, nullable=False)
    oportunidade_valor: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    oportunidade_conta_no_teto: Mapped[bool] = mapped_column(Boolean, nullable=False)


class TaxaRow(Base):
    """`taxa_pct` NULL = "igual" (usa a Mastercard); `chave` = '1'..'21' ou 'debito'."""

    __tablename__ = "taxas"
    __table_args__ = (
        UniqueConstraint("loja_id", "chave", "bandeira", name="loja_chave_bandeira"),
        CheckConstraint("taxa_pct IS NULL OR taxa_pct >= 0", name="taxa_nao_negativa"),
    )

    id: Mapped[uuid.UUID] = _pk()
    loja_id: Mapped[uuid.UUID] = _loja_fk()
    chave: Mapped[str] = mapped_column(String(16), nullable=False)
    bandeira: Mapped[str] = mapped_column(String(16), nullable=False)
    taxa_pct: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))


class TrocaRow(Base):
    """Linha da tabela de troca. SEM = coluna `desconto_<x>` NULL + `desconto_<x>_sem` true."""

    __tablename__ = "tabela_troca"
    __table_args__ = (
        UniqueConstraint("loja_id", "marca", "modelo", "capacidade_gb", name="loja_modelo_cap"),
        _sem_ck("tela"),
        _sem_ck("traseira"),
        _sem_ck("carcaca"),
        _sem_ck("bateria"),
        CheckConstraint("limite_bateria_pct >= 0 AND limite_bateria_pct <= 100", name="limite_ok"),
    )

    id: Mapped[uuid.UUID] = _pk()
    loja_id: Mapped[uuid.UUID] = _loja_fk()
    posicao: Mapped[int] = mapped_column(Integer, nullable=False)
    marca: Mapped[str] = mapped_column(String(100), nullable=False)
    modelo: Mapped[str] = mapped_column(String(200), nullable=False)
    capacidade_gb: Mapped[int] = mapped_column(Integer, nullable=False)
    valor_sem_detalhes: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    desconto_tela: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    desconto_tela_sem: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    desconto_traseira: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    desconto_traseira_sem: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    desconto_carcaca: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    desconto_carcaca_sem: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    desconto_bateria: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    desconto_bateria_sem: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    limite_bateria_pct: Mapped[int] = mapped_column(Integer, nullable=False)


class EstoqueLocalRow(Base):
    __tablename__ = "estoque_local"
    __table_args__ = (
        UniqueConstraint("loja_id", "sku", name="loja_sku"),
        CheckConstraint("condicao IN ('novo', 'seminovo')", name="condicao_valida"),
        CheckConstraint("quantidade >= 0", name="quantidade_nao_negativa"),
        CheckConstraint(
            "bateria_pct IS NULL OR (bateria_pct >= 0 AND bateria_pct <= 100)", name="bateria_ok"
        ),
    )

    id: Mapped[uuid.UUID] = _pk()
    loja_id: Mapped[uuid.UUID] = _loja_fk()
    posicao: Mapped[int] = mapped_column(Integer, nullable=False)
    sku: Mapped[str] = mapped_column(String(100), nullable=False)
    modelo: Mapped[str] = mapped_column(String(200), nullable=False)
    marca: Mapped[str] = mapped_column(String(100), nullable=False)
    capacidade_gb: Mapped[int] = mapped_column(Integer, nullable=False)
    cor: Mapped[str] = mapped_column(String(100), nullable=False)
    condicao: Mapped[str] = mapped_column(String(16), nullable=False)
    preco_pix: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    quantidade: Mapped[int] = mapped_column(Integer, nullable=False)
    bateria_pct: Mapped[int | None] = mapped_column(Integer)


class MapeamentoSkuRow(Base):
    __tablename__ = "mapeamento_sku"
    __table_args__ = (
        UniqueConstraint("loja_id", "sku_externo", name="loja_sku_externo"),
        CheckConstraint("condicao IN ('novo', 'seminovo')", name="condicao_valida"),
    )

    id: Mapped[uuid.UUID] = _pk()
    loja_id: Mapped[uuid.UUID] = _loja_fk()
    posicao: Mapped[int] = mapped_column(Integer, nullable=False)
    sku_externo: Mapped[str] = mapped_column(String(100), nullable=False)
    modelo: Mapped[str] = mapped_column(String(200), nullable=False)
    marca: Mapped[str] = mapped_column(String(100), nullable=False)
    capacidade_gb: Mapped[int] = mapped_column(Integer, nullable=False)
    cor: Mapped[str] = mapped_column(String(100), nullable=False)
    condicao: Mapped[str] = mapped_column(String(16), nullable=False)
