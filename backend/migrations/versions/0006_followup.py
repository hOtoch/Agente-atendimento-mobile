"""follow-up automatico: configuracao por loja

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-21 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "config_followup",
        sa.Column("loja_id", sa.Uuid(), nullable=False),
        sa.Column("ligado", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "horas_por_etapa",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("max_tentativas", sa.Integer(), server_default=sa.text("2"), nullable=False),
        sa.Column("intervalo_horas", sa.Integer(), server_default=sa.text("24"), nullable=False),
        sa.Column("hora_inicio", sa.Time(), server_default=sa.text("'09:00'"), nullable=False),
        sa.Column("hora_fim", sa.Time(), server_default=sa.text("'18:00'"), nullable=False),
        sa.Column("max_dias_parado", sa.Integer(), server_default=sa.text("7"), nullable=False),
        sa.CheckConstraint(
            "max_tentativas >= 1 AND max_tentativas <= 5",
            name=op.f("ck_config_followup_max_tentativas_ok"),
        ),
        sa.CheckConstraint("intervalo_horas >= 1", name=op.f("ck_config_followup_intervalo_ok")),
        sa.CheckConstraint("hora_inicio < hora_fim", name=op.f("ck_config_followup_horario_ok")),
        sa.CheckConstraint("max_dias_parado >= 1", name=op.f("ck_config_followup_max_dias_ok")),
        sa.ForeignKeyConstraint(
            ["loja_id"],
            ["lojas.id"],
            name=op.f("fk_config_followup_loja_id_lojas"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("loja_id", name=op.f("pk_config_followup")),
    )
    op.create_index(
        "ix_eventos_followup_lead",
        "eventos",
        ["lead_id", "criado_em"],
        postgresql_where=sa.text("tipo = 'followup'"),
    )


def downgrade() -> None:
    op.drop_index("ix_eventos_followup_lead", table_name="eventos")
    op.drop_table("config_followup")
