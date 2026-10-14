"""S-66 optimistic operation/configuration revision."""

import sqlalchemy as sa
from alembic import op

revision = "c230023a2026"
down_revision = "b220022a2026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "stations",
        sa.Column("status_version", sa.Integer(), server_default="1", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("stations", "status_version")
