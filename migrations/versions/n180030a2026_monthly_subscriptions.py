"""Monthly station subscriptions and distinct energy rates."""

import sqlalchemy as sa
from alembic import op

revision = "n180030a2026"
down_revision = "m170029a2026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "subscription_plans",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("station_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("monthly_fee_vnd", sa.BigInteger(), nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("monthly_fee_vnd > 0", name="ck_subscription_plan_fee"),
        sa.CheckConstraint("btrim(name) <> ''", name="ck_subscription_plan_name"),
        sa.ForeignKeyConstraint(["station_id"], ["stations.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_subscription_plans_station_active",
        "subscription_plans",
        ["station_id", "active"],
    )
    op.create_table(
        "subscription_plan_bands",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("plan_id", sa.Uuid(), nullable=False),
        sa.Column("start_min", sa.Integer(), nullable=False),
        sa.Column("end_min", sa.Integer(), nullable=False),
        sa.Column("energy_rate_vnd_per_kwh", sa.BigInteger(), nullable=False),
        sa.Column("label", sa.String(length=100), nullable=False),
        sa.CheckConstraint(
            "start_min >= 0 AND start_min < end_min AND end_min <= 1440",
            name="ck_subscription_bands_minute_range",
        ),
        sa.CheckConstraint(
            "energy_rate_vnd_per_kwh >= 0",
            name="ck_subscription_bands_rate_nonnegative",
        ),
        sa.CheckConstraint("btrim(label) <> ''", name="ck_subscription_bands_label"),
        sa.ForeignKeyConstraint(
            ["plan_id"], ["subscription_plans.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_subscription_plan_bands_plan_id",
        "subscription_plan_bands",
        ["plan_id"],
    )
    op.create_table(
        "driver_subscriptions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("driver_id", sa.Uuid(), nullable=False),
        sa.Column("station_id", sa.Uuid(), nullable=False),
        sa.Column("plan_id", sa.Uuid(), nullable=False),
        sa.Column(
            "status", sa.String(length=20), server_default="active", nullable=False
        ),
        sa.Column("current_period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("next_billing_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('active', 'past_due', 'cancelled')",
            name="ck_driver_subscription_status",
        ),
        sa.CheckConstraint(
            "current_period_start < current_period_end",
            name="ck_driver_subscription_period",
        ),
        sa.ForeignKeyConstraint(["driver_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["station_id"], ["stations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["plan_id"], ["subscription_plans.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_driver_subscription_station_active",
        "driver_subscriptions",
        ["driver_id", "station_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('active', 'past_due')"),
    )
    op.create_index(
        "ix_driver_subscriptions_due",
        "driver_subscriptions",
        ["status", "next_billing_at"],
    )
    op.create_index(
        "ix_driver_subscriptions_driver_station",
        "driver_subscriptions",
        ["driver_id", "station_id", "current_period_end"],
    )
    op.add_column(
        "invoice_lines", sa.Column("subscription_plan_id", sa.Uuid(), nullable=True)
    )
    op.create_foreign_key(
        "fk_invoice_lines_subscription_plan_id_subscription_plans",
        "invoice_lines",
        "subscription_plans",
        ["subscription_plan_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.drop_constraint("ck_wallet_ledger_entry_type", "wallet_ledger", type_="check")
    op.create_check_constraint(
        "ck_wallet_ledger_entry_type",
        "wallet_ledger",
        "entry_type IN ('gateway_topup', 'manual_topup', 'charging_debit', "
        "'adjustment', 'reservation_fee', 'subscription_debit')",
    )
    op.create_check_constraint(
        "ck_wallet_subscription_debit",
        "wallet_ledger",
        "entry_type <> 'subscription_debit' OR "
        "(amount_vnd < 0 AND reference_type = 'subscription')",
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM driver_subscriptions)
               OR EXISTS (SELECT 1 FROM subscription_plans)
               OR EXISTS (
                   SELECT 1 FROM wallet_ledger
                   WHERE entry_type = 'subscription_debit'
               )
               OR EXISTS (
                   SELECT 1 FROM invoice_lines
                   WHERE subscription_plan_id IS NOT NULL
               ) THEN
                RAISE EXCEPTION
                    'Cannot downgrade monthly subscriptions while subscription data exists';
            END IF;
        END
        $$;
        """
    )
    op.drop_constraint("ck_wallet_subscription_debit", "wallet_ledger", type_="check")
    op.drop_constraint("ck_wallet_ledger_entry_type", "wallet_ledger", type_="check")
    op.create_check_constraint(
        "ck_wallet_ledger_entry_type",
        "wallet_ledger",
        "entry_type IN ('gateway_topup', 'manual_topup', 'charging_debit', "
        "'adjustment', 'reservation_fee')",
    )
    op.drop_constraint(
        "fk_invoice_lines_subscription_plan_id_subscription_plans",
        "invoice_lines",
        type_="foreignkey",
    )
    op.drop_column("invoice_lines", "subscription_plan_id")
    op.drop_index(
        "ix_driver_subscriptions_driver_station", table_name="driver_subscriptions"
    )
    op.drop_index("ix_driver_subscriptions_due", table_name="driver_subscriptions")
    op.drop_index(
        "uq_driver_subscription_station_active", table_name="driver_subscriptions"
    )
    op.drop_table("driver_subscriptions")
    op.drop_index(
        "ix_subscription_plan_bands_plan_id", table_name="subscription_plan_bands"
    )
    op.drop_table("subscription_plan_bands")
    op.drop_index(
        "ix_subscription_plans_station_active", table_name="subscription_plans"
    )
    op.drop_table("subscription_plans")
