"""Persist account administration audit, without authentication secrets."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "b610003a2026"
down_revision = "a4d901ce8207"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "account_audits",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("target_id", sa.Uuid(), nullable=False),
        sa.Column("action", sa.String(40), nullable=False),
        sa.Column("before_state", postgresql.JSONB(), nullable=True),
        sa.Column("after_state", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "action IN ('account_created', 'account_updated')",
            name="ck_account_audits_action",
        ),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["target_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("actor_id", "target_id", "created_at"):
        op.create_index(f"ix_account_audits_{column}", "account_audits", [column])


def downgrade() -> None:
    op.drop_table("account_audits")
