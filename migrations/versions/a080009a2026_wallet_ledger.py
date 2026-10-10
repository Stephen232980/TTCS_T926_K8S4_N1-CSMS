"""Wallets and append-only integer-dong ledger (S-41 / T-84)."""

import sqlalchemy as sa
from alembic import op

revision = "a080009a2026"
down_revision = "f070008a2026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "wallets",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "driver_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("balance_vnd", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("status", sa.String(20), server_default="active", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("driver_id", name="uq_wallets_driver"),
        sa.CheckConstraint("status IN ('active', 'locked')", name="ck_wallets_status"),
    )
    op.create_table(
        "wallet_ledger",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "wallet_id",
            sa.Uuid(),
            sa.ForeignKey("wallets.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("entry_type", sa.String(30), nullable=False),
        sa.Column("amount_vnd", sa.BigInteger(), nullable=False),
        sa.Column("balance_after_vnd", sa.BigInteger(), nullable=False),
        sa.Column("reference_type", sa.String(50), nullable=False),
        sa.Column("reference_id", sa.String(128), nullable=False),
        sa.Column(
            "actor_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "entry_type IN ('gateway_topup', 'manual_topup', 'charging_debit', 'adjustment')",
            name="ck_wallet_ledger_entry_type",
        ),
        sa.CheckConstraint(
            "btrim(reference_type) <> '' AND btrim(reference_id) <> ''",
            name="ck_wallet_ledger_reference_nonempty",
        ),
        sa.UniqueConstraint(
            "entry_type", "reference_id", name="uq_wallet_ledger_reference"
        ),
        sa.CheckConstraint(
            "entry_type <> 'adjustment' OR (actor_id IS NOT NULL AND reference_type = 'audit')",
            name="ck_wallet_ledger_adjustment_audit",
        ),
    )
    op.create_index(
        "ix_wallet_ledger_wallet_id_id_desc",
        "wallet_ledger",
        ["wallet_id", sa.text("id DESC")],
    )
    # Match T-57: protect even the existing application/table owner, while
    # separate runtime roles can additionally receive only SELECT/INSERT.
    op.execute("""CREATE FUNCTION reject_wallet_ledger_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN RAISE EXCEPTION 'wallet ledger is append-only'; END; $$""")
    op.execute("""CREATE TRIGGER immutable_wallet_ledger
        BEFORE UPDATE OR DELETE OR TRUNCATE ON wallet_ledger
        FOR EACH STATEMENT EXECUTE FUNCTION reject_wallet_ledger_mutation()""")
    op.execute("REVOKE UPDATE, DELETE, TRUNCATE ON wallet_ledger FROM PUBLIC")


def downgrade() -> None:
    op.drop_table("wallet_ledger")
    op.execute("DROP FUNCTION reject_wallet_ledger_mutation()")
    op.drop_table("wallets")
