"""S-54 station partner revenue-share contracts."""

import sqlalchemy as sa
from alembic import op

revision = "n170030a2026"
down_revision = "m170029a2026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "partner_contracts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "station_id",
            sa.Uuid(),
            sa.ForeignKey("stations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "owner_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("owner_share_bps", sa.Integer(), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "owner_share_bps BETWEEN 0 AND 10000",
            name="ck_partner_contracts_owner_share_bps",
        ),
        sa.CheckConstraint(
            "effective_to IS NULL OR effective_from <= effective_to",
            name="ck_partner_contracts_effective_range",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "station_id",
            "effective_from",
            name="uq_partner_contracts_station_effective_from",
        ),
    )
    op.create_index(
        "ix_partner_contracts_station_effective",
        "partner_contracts",
        ["station_id", "effective_from", "effective_to"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_partner_contracts_station_effective", table_name="partner_contracts"
    )
    op.drop_table("partner_contracts")
