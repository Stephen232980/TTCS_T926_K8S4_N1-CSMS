"""Add driver wallets and station charging prices."""

import sqlalchemy as sa
from alembic import op

revision = "a104walletbalance"
down_revision = "e030007a2026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "stations",
        sa.Column("price_vnd_per_kwh", sa.Numeric(12, 2), nullable=True),
    )
    op.create_check_constraint(
        "ck_stations_price_vnd_per_kwh_positive",
        "stations",
        "price_vnd_per_kwh IS NULL OR price_vnd_per_kwh > 0",
    )
    op.create_table(
        "driver_wallets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("driver_id", sa.Uuid(), nullable=False),
        sa.Column(
            "balance_vnd",
            sa.Numeric(14, 2),
            server_default="0",
            nullable=False,
        ),
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
        sa.CheckConstraint(
            "balance_vnd >= 0", name="ck_driver_wallets_balance_nonnegative"
        ),
        sa.ForeignKeyConstraint(["driver_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("driver_id"),
    )


def downgrade() -> None:
    op.drop_table("driver_wallets")
    op.drop_constraint(
        "ck_stations_price_vnd_per_kwh_positive", "stations", type_="check"
    )
    op.drop_column("stations", "price_vnd_per_kwh")
