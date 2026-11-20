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
