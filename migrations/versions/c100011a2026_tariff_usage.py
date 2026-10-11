"""Remember invoice usage for effective-tariff immutability (S-34 / T-68)."""

import sqlalchemy as sa
from alembic import op

revision = "c100011a2026"
down_revision = "b090010a2026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tariffs", sa.Column("used_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("tariffs", "used_at")
