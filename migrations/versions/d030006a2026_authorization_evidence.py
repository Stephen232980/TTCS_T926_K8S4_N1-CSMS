"""Persist backend authorization evidence; historic rows remain unknown."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "d030006a2026"
down_revision = "c630005a2026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ("account_audits", "ocpp_control_requests"):
        op.add_column(table, sa.Column("permission", sa.String(100), nullable=True))
        op.add_column(table, sa.Column("actor_roles", JSONB(), nullable=True))


def downgrade() -> None:
    for table in ("ocpp_control_requests", "account_audits"):
        op.drop_column(table, "actor_roles")
        op.drop_column(table, "permission")
