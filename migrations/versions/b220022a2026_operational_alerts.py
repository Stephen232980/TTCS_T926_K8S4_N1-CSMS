"""S-46 incident episodes and recoverable email outbox."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "b220022a2026"
down_revision = "a210021a2026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "alert_rule_states",
        sa.Column(
            "charge_point_id",
            sa.Uuid(),
            sa.ForeignKey("charge_points.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("armed", sa.Boolean(), nullable=False),
        sa.Column("online_since", sa.DateTime(timezone=True)),
        sa.Column("recovery_last_seen", sa.DateTime(timezone=True)),
        sa.Column("recovery_observations", sa.Integer(), nullable=False),
    )
    op.create_table(
        "operational_alerts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "charge_point_id",
            sa.Uuid(),
            sa.ForeignKey("charge_points.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recovered_at", sa.DateTime(timezone=True)),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True)),
        sa.Column(
            "acknowledged_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT")
        ),
        sa.Column("closed_at", sa.DateTime(timezone=True)),
        sa.Column(
            "closed_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT")
        ),
        sa.Column("close_reason", sa.String(500)),
        sa.Column("details", postgresql.JSONB(), nullable=False),
        sa.CheckConstraint(
            "kind IN ('offline','error_burst')", name="ck_operational_alert_kind"
        ),
        sa.CheckConstraint(
            "status IN ('open','acknowledged','closed')",
            name="ck_operational_alert_status",
        ),
    )
    op.create_index(
        "uq_operational_alert_active_charger",
        "operational_alerts",
        ["charge_point_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('open','acknowledged')"),
    )
    op.create_index("ix_operational_alert_opened", "operational_alerts", ["opened_at"])
    op.create_table(
        "alert_emails",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "alert_id",
            sa.Uuid(),
            sa.ForeignKey("operational_alerts.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("recipient", sa.String(320), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True)),
        sa.Column("lease_token", sa.Uuid()),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.String(40)),
        sa.CheckConstraint(
            "status IN ('pending','sending','retry','sent','failed')",
            name="ck_alert_email_status",
        ),
        sa.CheckConstraint("attempts >= 0", name="ck_alert_email_attempts"),
    )
    op.create_index(
        "uq_alert_email_recipient",
        "alert_emails",
        ["alert_id", "recipient"],
        unique=True,
    )
    op.create_index("ix_alert_email_due", "alert_emails", ["status", "next_attempt_at"])


def downgrade() -> None:
    op.drop_table("alert_emails")
    op.drop_table("operational_alerts")
    op.drop_table("alert_rule_states")
