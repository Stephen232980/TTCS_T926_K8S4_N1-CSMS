"""S-28: source-clock occupation history and unplug-gated billing."""

import sqlalchemy as sa
from alembic import op

revision = "d170017a2026"
down_revision = "c160016a2026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Preserve invoices and the old policy for sessions already created at cutover.
    op.add_column(
        "charging_sessions",
        sa.Column(
            "billing_lifecycle_version",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.alter_column(
        "charging_sessions", "billing_lifecycle_version", server_default="1"
    )
    op.add_column(
        "charging_sessions",
        sa.Column(
            "release_detection",
            sa.String(20),
            nullable=False,
            server_default="explicit",
        ),
    )
    op.add_column(
        "charging_sessions",
        sa.Column("connector_released_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "charging_occupation_intervals",
        sa.Column("id", sa.Integer(), sa.Identity(), primary_key=True),
        sa.Column(
            "session_id",
            sa.Integer(),
            sa.ForeignKey("charging_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True)),
        sa.Column("confirmed", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("end_reason", sa.String(20)),
        sa.CheckConstraint(
            "ended_at IS NULL OR ended_at >= started_at", name="ck_occupation_time"
        ),
    )
    op.create_index(
        "ix_occupation_session", "charging_occupation_intervals", ["session_id"]
    )
    op.create_index(
        "ix_charging_sessions_connector_latest",
        "charging_sessions",
        ["connector_id", "id"],
    )
    op.create_check_constraint(
        "ck_charging_billing_version",
        "charging_sessions",
        "billing_lifecycle_version IN (0, 1)",
    )
    op.create_check_constraint(
        "ck_charging_release_detection",
        "charging_sessions",
        "release_detection IN ('explicit', 'available')",
    )
    op.create_check_constraint(
        "ck_charging_release_time",
        "charging_sessions",
        "connector_released_at IS NULL OR connector_released_at >= started_at",
    )
    op.create_index(
        "uq_occupation_open",
        "charging_occupation_intervals",
        ["session_id"],
        unique=True,
        postgresql_where=sa.text("ended_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_table("charging_occupation_intervals")
    op.drop_index(
        "ix_charging_sessions_connector_latest", table_name="charging_sessions"
    )
    op.drop_constraint("ck_charging_release_time", "charging_sessions", type_="check")
    op.drop_constraint(
        "ck_charging_release_detection", "charging_sessions", type_="check"
    )
    op.drop_constraint(
        "ck_charging_billing_version", "charging_sessions", type_="check"
    )
    op.drop_column("charging_sessions", "connector_released_at")
    op.drop_column("charging_sessions", "release_detection")
    op.drop_column("charging_sessions", "billing_lifecycle_version")
