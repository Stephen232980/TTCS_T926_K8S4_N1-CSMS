"""S-59 durable driver inbox and retryable email intent."""

from pathlib import Path

from alembic import op

revision = "m170029a2026"
down_revision = "l170028a2026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(Path(__file__).with_suffix(".sql").read_text(encoding="utf8"))


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER privacy_driver_notifications ON users; DROP FUNCTION purge_driver_notifications(); DROP TABLE driver_notifications"
    )
