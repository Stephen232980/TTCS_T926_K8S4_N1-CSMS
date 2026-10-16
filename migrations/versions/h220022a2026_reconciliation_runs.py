"""S-53: reconciliation runs and issues for energy vs money audit."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "h220022a2026"
down_revision = "g210021a2026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "reconciliation_runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "period_type", sa.String(length=20), nullable=False, server_default="month"
        ),
        sa.Column("date_from", sa.Date(), nullable=False),
        sa.Column("date_to", sa.Date(), nullable=False),
        sa.Column(
            "station_id",
            sa.Uuid(),
            sa.ForeignKey("stations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("cutoff_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "created_by",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "status", sa.String(length=20), nullable=False, server_default="completed"
        ),
        sa.Column("total_sessions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("matched_sessions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "mismatch_sessions", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "missing_data_sessions", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "total_meter_kwh",
            sa.Numeric(24, 6),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "total_billed_kwh",
            sa.Numeric(24, 6),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "kwh_discrepancy",
            sa.Numeric(24, 6),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "total_billed_vnd", sa.BigInteger(), nullable=False, server_default="0"
        ),
        sa.Column(
            "total_recomputed_vnd", sa.BigInteger(), nullable=False, server_default="0"
        ),
        sa.Column(
            "total_debited_vnd", sa.BigInteger(), nullable=False, server_default="0"
        ),
        sa.Column(
            "money_discrepancy_vnd", sa.BigInteger(), nullable=False, server_default="0"
        ),
        sa.Column(
            "summary_counts",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "algorithm_version",
            sa.String(length=20),
            nullable=False,
            server_default="1.0",
        ),
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        sa.CheckConstraint(
            "date_from <= date_to", name="ck_reconciliation_runs_date_range"
        ),
        sa.CheckConstraint(
            "total_sessions >= 0", name="ck_reconciliation_runs_total_sessions"
        ),
    )
    op.create_index(
        "ix_reconciliation_runs_created", "reconciliation_runs", ["created_at"]
    )

    op.create_table(
        "reconciliation_run_issues",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "run_id",
            sa.Uuid(),
            sa.ForeignKey("reconciliation_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "session_id",
            sa.Integer(),
            sa.ForeignKey("charging_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "station_id",
            sa.Uuid(),
            sa.ForeignKey("stations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("issue_type", sa.String(length=50), nullable=False),
        sa.Column("severity", sa.String(length=20), nullable=False),
        sa.Column("billed_vnd", sa.BigInteger(), nullable=True),
        sa.Column("recomputed_vnd", sa.BigInteger(), nullable=True),
        sa.Column("debited_vnd", sa.BigInteger(), nullable=True),
        sa.Column("money_difference_vnd", sa.BigInteger(), nullable=True),
        sa.Column("meter_kwh", sa.Numeric(24, 6), nullable=True),
        sa.Column("billed_kwh", sa.Numeric(24, 6), nullable=True),
        sa.Column("kwh_difference", sa.Numeric(24, 6), nullable=True),
        sa.Column("details", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "severity IN ('critical', 'warning', 'info')",
            name="ck_reconciliation_issues_severity",
        ),
    )
    op.create_index(
        "ix_reconciliation_issues_run_id", "reconciliation_run_issues", ["run_id"]
    )
    op.create_index(
        "ix_reconciliation_issues_session_id",
        "reconciliation_run_issues",
        ["session_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_reconciliation_issues_session_id", table_name="reconciliation_run_issues"
    )
    op.drop_index(
        "ix_reconciliation_issues_run_id", table_name="reconciliation_run_issues"
    )
    op.drop_table("reconciliation_run_issues")
    op.drop_index("ix_reconciliation_runs_created", table_name="reconciliation_runs")
    op.drop_table("reconciliation_runs")
