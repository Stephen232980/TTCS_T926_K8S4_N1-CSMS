"""S-42..44 durable station power budgets and command intents."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "a210021a2026"
down_revision = "f200020a2026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "station_power",
        sa.Column(
            "station_id",
            sa.Uuid(),
            sa.ForeignKey("stations.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column("limit_w", sa.BigInteger(), nullable=False),
        sa.Column("applied_limit_w", sa.BigInteger(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("generation", sa.BigInteger(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("target_enabled", sa.Boolean(), nullable=False),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("zero_limit_verified", sa.Boolean(), nullable=False),
        sa.Column("offline_retention_verified", sa.Boolean(), nullable=False),
        sa.Column("verification_note", sa.String(500), nullable=False),
        sa.Column("issue", sa.String(80)),
        sa.Column("dirty_at", sa.DateTime(timezone=True)),
        sa.Column("last_plan_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "limit_w > 0 AND applied_limit_w > 0", name="ck_power_limits"
        ),
        sa.CheckConstraint("version > 0 AND generation >= 0", name="ck_power_versions"),
        sa.CheckConstraint(
            "state IN ('disabled','bootstrap','ready','applying','degraded','disable_pending')",
            name="ck_power_state",
        ),
    )
    op.create_table(
        "connector_power",
        sa.Column(
            "connector_id",
            sa.Uuid(),
            sa.ForeignKey("connectors.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column(
            "station_id",
            sa.Uuid(),
            sa.ForeignKey("station_power.station_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("rated_w", sa.BigInteger(), nullable=False),
        sa.Column(
            "profile_id",
            sa.Integer(),
            sa.Identity(maxvalue=1073741822),
            unique=True,
            nullable=False,
        ),
        sa.Column("confirmed_w", sa.BigInteger(), nullable=False),
        sa.Column("reserved_w", sa.BigInteger(), nullable=False),
        sa.Column("desired_w", sa.BigInteger(), nullable=False),
        sa.Column("baseline_boot_at", sa.DateTime(timezone=True)),
        sa.Column("pending_command_id", sa.Uuid()),
        sa.CheckConstraint(
            "rated_w > 0 AND confirmed_w >= 0 AND reserved_w >= confirmed_w",
            name="ck_connector_power",
        ),
    )
    op.create_index("ix_connector_power_station_id", "connector_power", ["station_id"])
    op.create_table(
        "power_commands",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "station_id",
            sa.Uuid(),
            sa.ForeignKey("station_power.station_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "connector_id",
            sa.Uuid(),
            sa.ForeignKey("connectors.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("generation", sa.BigInteger(), nullable=False),
        sa.Column("action", sa.String(40), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_power_commands_station_id", "power_commands", ["station_id"])


def downgrade() -> None:
    op.drop_table("power_commands")
    op.drop_table("connector_power")
    op.drop_table("station_power")
