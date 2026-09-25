"""initialize schema

Revision ID: c269e44aee59
Revises:
Create Date: 2026-09-23 18:49:43.740673

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "c269e44aee59"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""


def downgrade() -> None:
    """Downgrade schema."""
