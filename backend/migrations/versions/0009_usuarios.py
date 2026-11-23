"""usuarios (login por loja)

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-23 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "usuarios",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("loja_id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("senha_hash", sa.Text(), nullable=False),
        sa.Column(
            "senha_provisoria", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("ativo", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "criado_em", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("ultimo_login_em", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("email = lower(email)", name=op.f("ck_usuarios_email_minusculo")),
        sa.ForeignKeyConstraint(
            ["loja_id"], ["lojas.id"], name=op.f("fk_usuarios_loja_id_lojas"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_usuarios")),
        sa.UniqueConstraint("email", name=op.f("uq_usuarios_email")),
    )
    op.create_index(op.f("ix_usuarios_loja_id"), "usuarios", ["loja_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_usuarios_loja_id"), table_name="usuarios")
    op.drop_table("usuarios")
