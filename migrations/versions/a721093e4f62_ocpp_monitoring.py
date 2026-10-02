"""Persist negotiated heartbeat and charger-level status.

Revision ID: a721093e4f62
Revises: 9c02a6b7d831
"""

import sqlalchemy as sa
from alembic import op

revision = "a721093e4f62"
down_revision = "9c02a6b7d831"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "charge_points",
        sa.Column(
            "heartbeat_interval_seconds",
            sa.Integer(),
            server_default="60",
            nullable=False,
        ),
    )
    for name, length in (
        ("raw_ocpp_status", 50),
        ("error_code", 100),
        ("vendor_error_code", 255),
    ):
        op.add_column(
            "charge_points", sa.Column(name, sa.String(length), nullable=True)
        )
    op.add_column(
        "charge_points",
        sa.Column("error_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        "ck_charge_points_heartbeat_positive",
        "charge_points",
        "heartbeat_interval_seconds > 0",
    )
    op.create_index("ix_charge_points_last_seen_at", "charge_points", ["last_seen_at"])


def downgrade() -> None:
    op.drop_index("ix_charge_points_last_seen_at", table_name="charge_points")
    op.drop_constraint("ck_charge_points_heartbeat_positive", "charge_points")
    for name in (
        "error_at",
        "vendor_error_code",
        "error_code",
        "raw_ocpp_status",
        "heartbeat_interval_seconds",
    ):
        op.drop_column("charge_points", name)
