"""S-50: fee snapshots and immutable wallet reservation debits."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "e250025a2026"
down_revision = "d240024a2026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "reservation_policies",
        sa.Column(
            "station_id",
            postgresql.UUID(),
            sa.ForeignKey("stations.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column("fee_vnd", sa.BigInteger(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "fee_vnd >= 0 AND fee_vnd <= 1000000", name="ck_reservation_policy_fee"
        ),
        sa.CheckConstraint("version > 0", name="ck_reservation_policy_version"),
    )
    for column in (
        sa.Column("fee_vnd", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column(
            "fee_policy_version", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "fee_decision",
            sa.String(24),
            nullable=False,
            server_default="legacy_exempt",
        ),
        sa.Column("fee_reason", sa.String(60)),
        sa.Column("fee_decided_at", sa.DateTime(timezone=True)),
        sa.Column("fee_ledger_id", sa.BigInteger()),
        sa.Column("activated_at", sa.DateTime(timezone=True)),
        sa.Column("expiry_fee_eligible", sa.Boolean()),
    ):
        op.add_column("reservations", column)
    op.alter_column("reservations", "fee_decision", server_default="pending")
    op.create_foreign_key(
        "fk_reservation_fee_ledger",
        "reservations",
        "wallet_ledger",
        ["fee_ledger_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_unique_constraint(
        "uq_reservation_fee_ledger", "reservations", ["fee_ledger_id"]
    )
    op.create_check_constraint(
        "ck_reservation_fee_amount",
        "reservations",
        "fee_vnd >= 0 AND fee_vnd <= 1000000",
    )
    op.create_check_constraint(
        "ck_reservation_fee_decision",
        "reservations",
        "fee_decision IN ('pending','legacy_exempt','waived','charged','review')",
    )
    op.create_index(
        "ix_reservation_fee_due", "reservations", ["fee_decision", "expires_at"]
    )
    op.drop_constraint("ck_wallet_ledger_entry_type", "wallet_ledger", type_="check")
    op.create_check_constraint(
        "ck_wallet_ledger_entry_type",
        "wallet_ledger",
        "entry_type IN ('gateway_topup','manual_topup','charging_debit','adjustment','reservation_fee')",
    )
    op.create_check_constraint(
        "ck_wallet_reservation_fee",
        "wallet_ledger",
        "entry_type <> 'reservation_fee' OR (amount_vnd < 0 AND reference_type = 'reservation')",
    )


def downgrade() -> None:
    # Never discard immutable financial entries just to make an old enum fit.
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM wallet_ledger WHERE entry_type='reservation_fee') THEN RAISE EXCEPTION 'reservation fees exist; financial downgrade requires reconciliation'; END IF; END $$"
    )
    op.drop_constraint("ck_wallet_reservation_fee", "wallet_ledger", type_="check")
    op.drop_constraint("ck_wallet_ledger_entry_type", "wallet_ledger", type_="check")
    op.create_check_constraint(
        "ck_wallet_ledger_entry_type",
        "wallet_ledger",
        "entry_type IN ('gateway_topup','manual_topup','charging_debit','adjustment')",
    )
    op.drop_index("ix_reservation_fee_due", table_name="reservations")
    for name, kind in (
        ("ck_reservation_fee_decision", "check"),
        ("ck_reservation_fee_amount", "check"),
        ("uq_reservation_fee_ledger", "unique"),
        ("fk_reservation_fee_ledger", "foreignkey"),
    ):
        op.drop_constraint(name, "reservations", type_=kind)
    for name in (
        "expiry_fee_eligible",
        "activated_at",
        "fee_ledger_id",
        "fee_decided_at",
        "fee_reason",
        "fee_decision",
        "fee_policy_version",
        "fee_vnd",
    ):
        op.drop_column("reservations", name)
    op.drop_table("reservation_policies")
