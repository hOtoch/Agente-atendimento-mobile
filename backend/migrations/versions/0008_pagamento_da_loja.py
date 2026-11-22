"""formas de pagamento aceitas e chave Pix da loja

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-22 14:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Sem linha a loja usa o padrao do codigo (Pix, debito e credito aceitos, sem chave): as
    # lojas existentes seguem como estavam, sem backfill.
    op.create_table(
        "pagamento_loja",
        sa.Column("loja_id", sa.Uuid(), nullable=False),
        sa.Column("aceita_pix", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("aceita_debito", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("aceita_credito", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("chave_pix_tipo", sa.String(length=16), nullable=True),
        sa.Column("chave_pix", sa.String(length=100), nullable=True),
        sa.Column("chave_pix_favorecido", sa.String(length=100), nullable=True),
        sa.CheckConstraint(
            "chave_pix_tipo IS NULL OR chave_pix_tipo IN "
            "('cpf', 'cnpj', 'email', 'telefone', 'aleatoria')",
            name=op.f("ck_pagamento_loja_chave_pix_tipo_valido"),
        ),
        sa.CheckConstraint(
            "(chave_pix_tipo IS NULL AND chave_pix IS NULL AND chave_pix_favorecido IS NULL) OR "
            "(chave_pix_tipo IS NOT NULL AND chave_pix IS NOT NULL "
            "AND chave_pix_favorecido IS NOT NULL)",
            name=op.f("ck_pagamento_loja_chave_pix_completa_ou_vazia"),
        ),
        sa.ForeignKeyConstraint(
            ["loja_id"],
            ["lojas.id"],
            name=op.f("fk_pagamento_loja_loja_id_lojas"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("loja_id", name=op.f("pk_pagamento_loja")),
    )


def downgrade() -> None:
    op.drop_table("pagamento_loja")
