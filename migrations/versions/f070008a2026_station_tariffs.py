"""Versioned tariffs and integer-minute price bands (S-28 / T-59)."""

import sqlalchemy as sa
from alembic import op

revision = "f070008a2026"
down_revision = "e030007a2026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tariffs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("station_id", sa.Uuid(), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("idle_rate_vnd_per_minute", sa.BigInteger(), nullable=False),
        sa.Column("grace_minutes", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["station_id"], ["stations.id"], ondelete="RESTRICT"),
        # PostgreSQL also creates the composite index used for effective-date lookup.
        sa.UniqueConstraint(
            "station_id", "effective_from", name="uq_tariffs_station_effective_from"
        ),
        sa.CheckConstraint(
            "idle_rate_vnd_per_minute >= 0", name="ck_tariffs_idle_rate_nonnegative"
        ),
        sa.CheckConstraint("grace_minutes >= 0", name="ck_tariffs_grace_nonnegative"),
    )
    op.create_table(
        "tariff_bands",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tariff_id", sa.Uuid(), nullable=False),
        sa.Column("start_min", sa.Integer(), nullable=False),
        sa.Column("end_min", sa.Integer(), nullable=False),
        sa.Column("energy_rate_vnd_per_kwh", sa.BigInteger(), nullable=False),
        sa.Column("label", sa.String(100), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["tariff_id"], ["tariffs.id"], ondelete="RESTRICT"),
        sa.CheckConstraint(
            "start_min >= 0 AND start_min < end_min AND end_min <= 1440",
            name="ck_tariff_bands_minute_range",
        ),
        sa.CheckConstraint(
            "energy_rate_vnd_per_kwh >= 0",
            name="ck_tariff_bands_energy_rate_nonnegative",
        ),
    )
    op.create_index("ix_tariff_bands_tariff_id", "tariff_bands", ["tariff_id"])


def downgrade() -> None:
    op.drop_index("ix_tariff_bands_tariff_id", table_name="tariff_bands")
    op.drop_table("tariff_bands")
    op.drop_table("tariffs")
