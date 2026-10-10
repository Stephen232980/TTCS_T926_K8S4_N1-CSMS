"""Immutable wallet administrative evidence supporting T-86 / T-87."""

import sqlalchemy as sa
from alembic import op

revision = "b090010a2026"
down_revision = "a080009a2026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "wallet_audits",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "wallet_id",
            sa.Uuid(),
            sa.ForeignKey("wallets.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "actor_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("action", sa.String(40), nullable=False),
        sa.Column("before_balance_vnd", sa.BigInteger(), nullable=False),
        sa.Column("after_balance_vnd", sa.BigInteger(), nullable=False),
        sa.Column("amount_vnd", sa.BigInteger()),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "action IN ('cache_repaired', 'adjustment_authorized')",
            name="ck_wallet_audits_action",
        ),
        sa.CheckConstraint("btrim(reason) <> ''", name="ck_wallet_audits_reason"),
        sa.CheckConstraint(
            "(action = 'cache_repaired' AND amount_vnd IS NULL) OR (action = 'adjustment_authorized' AND amount_vnd IS NOT NULL AND amount_vnd <> 0 AND after_balance_vnd::numeric = before_balance_vnd::numeric + amount_vnd::numeric)",
            name="ck_wallet_audits_amount",
        ),
    )
    op.create_index(
        "ix_wallet_audits_wallet_created", "wallet_audits", ["wallet_id", "created_at"]
    )
    op.execute("""CREATE TRIGGER immutable_wallet_audits
        BEFORE UPDATE OR DELETE OR TRUNCATE ON wallet_audits
        FOR EACH STATEMENT EXECUTE FUNCTION reject_wallet_ledger_mutation()""")
    op.execute("REVOKE UPDATE, DELETE, TRUNCATE ON wallet_audits FROM PUBLIC")


def downgrade() -> None:
    op.drop_table("wallet_audits")
