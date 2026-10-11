"""T-63: source-ordered connector status and the final idle interval."""

import sqlalchemy as sa
from alembic import op

revision = "c160016a2026"
down_revision = "b150015a2026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "charging_sessions",
        sa.Column("idle_since", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "connectors",
        sa.Column(
            "last_status_notification_at", sa.DateTime(timezone=True), nullable=True
        ),
    )


def downgrade() -> None:
    op.drop_column("connectors", "last_status_notification_at")
    op.drop_column("charging_sessions", "idle_since")
