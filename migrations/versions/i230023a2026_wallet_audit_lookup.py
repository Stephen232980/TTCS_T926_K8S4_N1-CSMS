"""S-56 wallet audit lookup indexes; historical evidence remains untouched."""

from alembic import op

revision = "i230023a2026"
down_revision = "h220022a2026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX ix_audit_wallet_lookup ON audit_logs (action, occurred_at DESC, id DESC) WHERE action IN ('wallet.manual_topup','wallet.adjusted','wallet.cache_repaired','wallet.unlocked','reservation.fee_decided')"
    )


def downgrade() -> None:
    op.drop_index("ix_audit_wallet_lookup", table_name="audit_logs")
