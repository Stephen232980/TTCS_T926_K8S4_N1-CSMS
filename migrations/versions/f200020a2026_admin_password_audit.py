"""Allow explicit credential-reset entries in the existing account audit."""

import sqlalchemy as sa
from alembic import op

revision = "f200020a2026"
down_revision = "e190019a2026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_account_audits_action", "account_audits", type_="check")
    op.create_check_constraint(
        "ck_account_audits_action",
        "account_audits",
        "action IN ('account_created', 'account_updated', 'account_password_reset')",
    )


def downgrade() -> None:
    count = op.get_bind().scalar(
        sa.text(
            "SELECT count(*) FROM account_audits WHERE action='account_password_reset'"
        )
    )
    if count:
        raise RuntimeError(
            "Cannot downgrade while credential-reset audit evidence exists"
        )
    op.drop_constraint("ck_account_audits_action", "account_audits", type_="check")
    op.create_check_constraint(
        "ck_account_audits_action",
        "account_audits",
        "action IN ('account_created', 'account_updated')",
    )
