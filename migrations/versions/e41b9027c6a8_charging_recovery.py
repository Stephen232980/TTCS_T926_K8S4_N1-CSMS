"""Recovery observations, abnormal sessions and audited manual closure."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "e41b9027c6a8"
down_revision = "d830a62f194b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for name in ("recovery_at", "abnormal_since", "manual_closed_at"):
        op.add_column("charging_sessions", sa.Column(name, sa.DateTime(timezone=True)))
    op.add_column("charging_sessions", sa.Column("manual_close_reason", sa.String(500)))
    op.add_column("charging_sessions", sa.Column("closed_by", sa.Uuid()))
    op.create_foreign_key(
        "fk_charging_sessions_closed_by",
        "charging_sessions",
        "users",
        ["closed_by"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_table(
        "charging_session_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "session_id",
            sa.Integer(),
            sa.ForeignKey("charging_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("action", sa.String(40), nullable=False),
        sa.Column(
            "actor_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT")
        ),
        sa.Column("details", postgresql.JSONB(), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_charging_session_events_session_id",
        "charging_session_events",
        ["session_id"],
    )


def downgrade() -> None:
    op.drop_table("charging_session_events")
    op.drop_constraint(
        "fk_charging_sessions_closed_by", "charging_sessions", type_="foreignkey"
    )
    for name in (
        "closed_by",
        "manual_close_reason",
        "manual_closed_at",
        "abnormal_since",
        "recovery_at",
    ):
        op.drop_column("charging_sessions", name)
