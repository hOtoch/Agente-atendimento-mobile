"""integracao com o ERP (Mercado Phone): conexao da loja e colunas de vinculo

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-22 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "conexao_erp",
        sa.Column("loja_id", sa.Uuid(), nullable=False),
        sa.Column(
            "provedor",
            sa.String(length=32),
            server_default=sa.text("'mercadophone'"),
            nullable=False,
        ),
        sa.Column("system_unit_id", sa.BigInteger(), nullable=False),
        sa.Column("filtro_loja", sa.Text(), nullable=True),
        sa.Column("ativo", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("intervalo_min", sa.Integer(), server_default=sa.text("15"), nullable=False),
        sa.Column(
            "exportar_handoff", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("ultima_sincronizacao_em", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ultimo_status", sa.String(length=32), nullable=True),
        sa.Column("ultimo_relatorio", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.CheckConstraint(
            "provedor IN ('mercadophone')", name=op.f("ck_conexao_erp_provedor_valido")
        ),
        sa.CheckConstraint("system_unit_id > 0", name=op.f("ck_conexao_erp_unidade_ok")),
        sa.CheckConstraint(
            "intervalo_min >= 5 AND intervalo_min <= 1440", name=op.f("ck_conexao_erp_intervalo_ok")
        ),
        sa.ForeignKeyConstraint(
            ["loja_id"],
            ["lojas.id"],
            name=op.f("fk_conexao_erp_loja_id_lojas"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("loja_id", name=op.f("pk_conexao_erp")),
    )
    op.add_column("estoque_local", sa.Column("erp_produto_id", sa.BigInteger(), nullable=True))
    op.add_column("vendedores", sa.Column("codigo_erp", sa.Text(), nullable=True))
    op.add_column("leads", sa.Column("erp_cliente_id", sa.BigInteger(), nullable=True))
    op.add_column("leads", sa.Column("erp_orcamento_id", sa.BigInteger(), nullable=True))


def downgrade() -> None:
    op.drop_column("leads", "erp_orcamento_id")
    op.drop_column("leads", "erp_cliente_id")
    op.drop_column("vendedores", "codigo_erp")
    op.drop_column("estoque_local", "erp_produto_id")
    op.drop_table("conexao_erp")
