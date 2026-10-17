"""S-57 durable privacy intake without enabling destructive execution."""

import sqlalchemy as sa
from alembic import op

revision = "h170026a2026"
down_revision = "g210021a2026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "privacy_requests",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), server_default="pending", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "reviewer_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT")
        ),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("decision_reason", sa.Text()),
        sa.Column("policy_version", sa.String(100)),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'rejected')",
            name="ck_privacy_request_status",
        ),
        sa.CheckConstraint(
            "status = 'pending' OR (reviewer_id IS NOT NULL AND reviewed_at IS NOT NULL AND decision_reason IS NOT NULL AND policy_version IS NOT NULL AND length(trim(decision_reason)) >= 3 AND length(trim(policy_version)) > 0)",
            name="ck_privacy_request_decision",
        ),
    )
    op.create_index("ix_privacy_requests_user_id", "privacy_requests", ["user_id"])
    op.create_index(
        "uq_privacy_request_active",
        "privacy_requests",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('pending', 'approved')"),
    )


def downgrade() -> None:
    op.drop_table("privacy_requests")
