"""autor da mensagem (cliente, ia ou vendedor)

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-20 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "mensagens",
        sa.Column(
            "autor", sa.String(length=16), server_default=sa.text("'cliente'"), nullable=False
        ),
    )
    # as mensagens que ja existem so podem ser do cliente (entrada) ou da IA (saida)
    op.execute(
        "UPDATE mensagens SET autor = CASE direcao WHEN 'entrada' THEN 'cliente' ELSE 'ia' END"
    )
    op.create_check_constraint(
        op.f("ck_mensagens_autor_valido"), "mensagens", "autor IN ('cliente', 'ia', 'vendedor')"
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_mensagens_autor_valido"), "mensagens", type_="check")
    op.drop_column("mensagens", "autor")
