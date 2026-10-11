"""Private driver virtual tags and durable start requests."""

import sqlalchemy as sa
from alembic import op

revision = "c60318a4d962"
down_revision = "f52c813d7a09"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "id_tags",
        sa.Column(
            "driver_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column(
            "card_id",
            sa.Uuid(),
            sa.ForeignKey("charging_cards.id", ondelete="RESTRICT"),
            nullable=False,
            unique=True,
        ),
        sa.Column("id_tag", sa.String(20), nullable=False, unique=True),
    )
    op.create_table(
        "driver_start_requests",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "driver_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "connector_id",
            sa.Uuid(),
            sa.ForeignKey("connectors.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "charge_point_id",
            sa.Uuid(),
            sa.ForeignKey("charge_points.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("reply_status", sa.String(30), nullable=False),
        sa.Column("reply_at", sa.DateTime(timezone=True)),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "session_id",
            sa.Integer(),
            sa.ForeignKey("charging_sessions.id", ondelete="SET NULL"),
        ),
    )
    op.create_index(
        "ix_driver_start_requests_driver_id", "driver_start_requests", ["driver_id"]
    )
    op.create_index(
        "ix_driver_start_requests_created_at", "driver_start_requests", ["created_at"]
    )
    for name in ("driver", "connector"):
        op.create_index(
            "uq_driver_start_pending_" + name,
            "driver_start_requests",
            [name + "_id"],
            unique=True,
            postgresql_where=sa.text("status IN ('Pending', 'Accepted')"),
        )


def downgrade() -> None:
    op.drop_table("driver_start_requests")
    op.drop_table("id_tags")
