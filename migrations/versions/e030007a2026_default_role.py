"""Explicit landing preference; never infer a priority for multi-role accounts."""

import sqlalchemy as sa
from alembic import op

revision = "e030007a2026"
down_revision = "d030006a2026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user_roles",
        sa.Column(
            "is_default", sa.Boolean(), server_default=sa.false(), nullable=False
        ),
    )
    op.execute(
        "UPDATE user_roles SET is_default = true WHERE user_id IN (SELECT user_id FROM user_roles GROUP BY user_id HAVING count(*) = 1)"
    )
    op.create_index(
        "uq_user_roles_default",
        "user_roles",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("is_default = true"),
    )


def downgrade() -> None:
    op.drop_index("uq_user_roles_default", table_name="user_roles")
    op.drop_column("user_roles", "is_default")
