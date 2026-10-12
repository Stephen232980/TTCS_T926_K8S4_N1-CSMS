"""T-106: retain the wallet snapshot that rejected a driver start."""

import sqlalchemy as sa
from alembic import op

revision = "e190019a2026"
down_revision = "4db8d8987c3a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("driver_start_requests", sa.Column("balance_vnd", sa.BigInteger()))
    op.add_column(
        "driver_start_requests", sa.Column("minimum_balance_vnd", sa.BigInteger())
    )


def downgrade() -> None:
    op.drop_column("driver_start_requests", "minimum_balance_vnd")
    op.drop_column("driver_start_requests", "balance_vnd")
