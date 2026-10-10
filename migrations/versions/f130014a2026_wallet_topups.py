"""T-91 payment attempts with database-enforced external identifiers."""

import sqlalchemy as sa
from alembic import op

revision = "f130014a2026"
down_revision = "e120013a2026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "wallet_topups",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "driver_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("amount_vnd", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(20), server_default="pending", nullable=False),
        sa.Column("order_id", sa.String(128), nullable=False),
        sa.Column("gateway_transaction_id", sa.String(128)),
        sa.Column("reason", sa.Text()),
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
        sa.UniqueConstraint("order_id", name="uq_wallet_topups_order"),
        sa.UniqueConstraint("gateway_transaction_id", name="uq_wallet_topups_gateway"),
        sa.CheckConstraint("amount_vnd > 0", name="ck_wallet_topups_amount"),
        sa.CheckConstraint(
            "status IN ('pending', 'succeeded', 'failed', 'cancelled', 'needs_review')",
            name="ck_wallet_topups_status",
        ),
        sa.CheckConstraint("btrim(order_id) <> ''", name="ck_wallet_topups_order"),
        sa.CheckConstraint(
            "gateway_transaction_id IS NULL OR btrim(gateway_transaction_id) <> ''",
            name="ck_wallet_topups_gateway",
        ),
    )
    op.create_index(
        "ix_wallet_topups_driver_created", "wallet_topups", ["driver_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_table("wallet_topups")
