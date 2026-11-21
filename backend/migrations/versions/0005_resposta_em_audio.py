"""responder em audio quando o cliente mandar audio (opcao por loja)

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-21 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "perfil_loja",
        sa.Column(
            "responder_em_audio", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
    )


def downgrade() -> None:
    op.drop_column("perfil_loja", "responder_em_audio")
