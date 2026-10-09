"""Add station charging prices for minimum-wallet eligibility."""

import sqlalchemy as sa
from alembic import op

revision = "a104walletbalance"
down_revision = "c160016a2026"
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

def downgrade() -> None:
    op.drop_constraint(
        "ck_stations_price_vnd_per_kwh_positive", "stations", type_="check"
    )
    op.drop_column("stations", "price_vnd_per_kwh")
