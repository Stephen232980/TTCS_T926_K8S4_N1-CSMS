"""tao bang charge_points va connectors

Revision ID: 5e8a9b0c1d2f
Revises: 8f2b1d3a4c5e
Create Date: 2026-09-28 18:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "5e8a9b0c1d2f"
down_revision: str | Sequence[str] | None = "8f2b1d3a4c5e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "charge_points",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("station_id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=150), nullable=True),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default="offline",
            nullable=False,
        ),
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
        sa.ForeignKeyConstraint(["station_id"], ["stations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", name="uq_charge_points_code"),
    )
    op.create_index(
        "ix_charge_points_code", "charge_points", ["code"], unique=True
    )
    op.create_index(
        "ix_charge_points_station_id", "charge_points", ["station_id"], unique=False
    )

    op.create_table(
        "connectors",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("charge_point_id", sa.Uuid(), nullable=False),
        sa.Column("connector_number", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=30),
            server_default="Available",
            nullable=False,
        ),
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
        sa.CheckConstraint(
            "connector_number >= 1",
            name="ck_connectors_connector_number_gte_1",
        ),
        sa.ForeignKeyConstraint(
            ["charge_point_id"], ["charge_points.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "charge_point_id",
            "connector_number",
            name="uq_connectors_cp_id_connector_number",
        ),
    )
    op.create_index(
        "ix_connectors_charge_point_id", "connectors", ["charge_point_id"], unique=False
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_connectors_charge_point_id", table_name="connectors")
    op.drop_table("connectors")
    op.drop_index("ix_charge_points_station_id", table_name="charge_points")
    op.drop_index("ix_charge_points_code", table_name="charge_points")
    op.drop_table("charge_points")
