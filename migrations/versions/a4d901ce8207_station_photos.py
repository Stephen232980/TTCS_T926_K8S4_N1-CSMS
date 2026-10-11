"""Store station representative photos transactionally."""

import sqlalchemy as sa
from alembic import op

revision = "a4d901ce8207"
down_revision = "c60318a4d962"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("stations", sa.Column("photo_data", sa.LargeBinary(), nullable=True))
    op.add_column("stations", sa.Column("photo_mime", sa.String(30), nullable=True))
    op.add_column("stations", sa.Column("photo_digest", sa.String(64), nullable=True))


def downgrade() -> None:
    op.drop_column("stations", "photo_digest")
    op.drop_column("stations", "photo_mime")
    op.drop_column("stations", "photo_data")
