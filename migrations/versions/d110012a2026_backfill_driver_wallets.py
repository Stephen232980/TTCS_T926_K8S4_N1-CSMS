"""Backfill missing driver wallets without changing existing financial data."""

from alembic import op

revision = "d110012a2026"
down_revision = "c100011a2026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""INSERT INTO wallets (id, driver_id, balance_vnd, status)
        SELECT gen_random_uuid(), ur.user_id, 0, 'active'
        FROM user_roles ur JOIN roles r ON r.id = ur.role_id
        WHERE r.code = 'driver'
        ON CONFLICT ON CONSTRAINT uq_wallets_driver DO NOTHING""")


def downgrade() -> None:
    # A provisioned wallet may already have immutable ledger entries. Retain it.
    pass
