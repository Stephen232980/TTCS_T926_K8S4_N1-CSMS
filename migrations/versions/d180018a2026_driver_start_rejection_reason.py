"""Persist wallet rejection reasons for driver start recovery."""

import sqlalchemy as sa
from alembic import op

revision = "d180018a2026"
down_revision = "d170017a2026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("driver_start_requests", sa.Column("rejection_reason", sa.String(32)))


def downgrade() -> None:
    op.drop_column("driver_start_requests", "rejection_reason")
