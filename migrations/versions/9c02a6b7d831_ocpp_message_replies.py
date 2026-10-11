"""Durable OCPP duplicate reply cache.

Revision ID: 9c02a6b7d831
Revises: 7b1d4f2a9c30
"""

import sqlalchemy as sa
from alembic import op

revision = "9c02a6b7d831"
down_revision = "7b1d4f2a9c30"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ocpp_message_replies",
        sa.Column(
            "charge_point_id",
            sa.Uuid(),
            sa.ForeignKey("charge_points.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("message_id", sa.String(36), primary_key=True),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("response", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_ocpp_message_replies_created_at", "ocpp_message_replies", ["created_at"]
    )


def downgrade() -> None:
    op.drop_table("ocpp_message_replies")
