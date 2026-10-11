"""Persist measured system health and aggregate OCPP telemetry."""

import sqlalchemy as sa
from alembic import op

revision = "c630005a2026"
down_revision = "b610003a2026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ocpp_telemetry_buckets",
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("worker_id", sa.Uuid(), nullable=False),
        sa.Column("error_count", sa.Integer(), nullable=False),
        sa.Column("response_count", sa.Integer(), nullable=False),
        sa.Column("latency_total_ms", sa.Float(), nullable=False),
        sa.Column("complete", sa.Boolean(), nullable=False),
        sa.CheckConstraint(
            "error_count >= 0 AND response_count >= 0 AND latency_total_ms >= 0",
            name="ck_ocpp_telemetry_nonnegative",
        ),
        sa.PrimaryKeyConstraint("timestamp", "worker_id"),
    )
    op.create_table(
        "system_health_samples",
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("online_charge_points", sa.Integer(), nullable=False),
        sa.Column("registered_charge_points", sa.Integer(), nullable=False),
        sa.Column("running_sessions", sa.Integer(), nullable=False),
        sa.Column("error_messages_5m", sa.Integer(), nullable=True),
        sa.Column("error_messages_observed_5m", sa.Integer(), nullable=False),
        sa.Column("response_count_5m", sa.Integer(), nullable=False),
        sa.Column("response_latency_ms", sa.Float(), nullable=True),
        sa.Column("window_complete", sa.Boolean(), nullable=False),
        sa.CheckConstraint(
            "online_charge_points >= 0 AND registered_charge_points >= 0 "
            "AND running_sessions >= 0 AND error_messages_observed_5m >= 0 "
            "AND response_count_5m >= 0 "
            "AND (error_messages_5m IS NULL OR error_messages_5m >= 0) "
            "AND (response_latency_ms IS NULL OR response_latency_ms >= 0)",
            name="ck_system_health_nonnegative",
        ),
        sa.PrimaryKeyConstraint("timestamp"),
    )


def downgrade() -> None:
    op.drop_table("system_health_samples")
    op.drop_table("ocpp_telemetry_buckets")
