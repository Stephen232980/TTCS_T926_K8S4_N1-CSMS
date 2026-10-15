"""Station power limit schedules by time bands (S-45 / G2)."""

import sqlalchemy as sa
from alembic import op

revision = "g210021a2026"
down_revision = "f200020a2026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "station_power_schedules",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("station_id", sa.Uuid(), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["station_id"], ["stations.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint(
            "station_id",
            "effective_from",
            name="uq_station_power_schedules_station_effective_from",
        ),
    )
    op.create_index(
        "ix_station_power_schedules_station_id",
        "station_power_schedules",
        ["station_id"],
    )

    op.create_table(
        "station_power_schedule_bands",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("schedule_id", sa.Uuid(), nullable=False),
        sa.Column("start_min", sa.Integer(), nullable=False),
        sa.Column("end_min", sa.Integer(), nullable=False),
        sa.Column("power_limit_w", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["schedule_id"], ["station_power_schedules.id"], ondelete="CASCADE"
        ),
        sa.CheckConstraint(
            "start_min >= 0 AND start_min < end_min AND end_min <= 1440",
            name="ck_station_power_schedule_bands_minute_range",
        ),
        sa.CheckConstraint(
            "power_limit_w > 0",
            name="ck_station_power_schedule_bands_power_positive",
        ),
    )
    op.create_index(
        "ix_station_power_schedule_bands_schedule_id",
        "station_power_schedule_bands",
        ["schedule_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_station_power_schedule_bands_schedule_id",
        table_name="station_power_schedule_bands",
    )
    op.drop_table("station_power_schedule_bands")
    op.drop_index(
        "ix_station_power_schedules_station_id",
        table_name="station_power_schedules",
    )
    op.drop_table("station_power_schedules")
