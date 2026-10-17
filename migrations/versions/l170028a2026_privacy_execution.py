"""S-57 policy, isolated subject vault and checkpointed privileged redaction."""

from pathlib import Path

from alembic import op

revision = "l170028a2026"
down_revision = "k170027a2026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(Path(__file__).with_suffix(".sql").read_text(encoding="utf-8"))


def downgrade() -> None:
    # Erasure must never be reversed by a schema rollback.
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM privacy_jobs WHERE checkpoint > 0) THEN RAISE EXCEPTION 'privacy execution exists; downgrade requires an explicit recovery plan'; END IF; END $$"
    )
    op.execute(
        Path(__file__)
        .with_name("l170028a2026_privacy_execution_down.sql")
        .read_text(encoding="utf-8")
    )
