"""S-60 durable configuration intents and verified readback."""

import sqlalchemy as sa
from alembic import op

revision = "j240024a2026"
down_revision = "i230023a2026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ocpp_configuration_intents",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "charge_point_id",
            sa.Uuid(),
            sa.ForeignKey("charge_points.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "actor_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("key", sa.String(50), nullable=False),
        sa.Column("value", sa.Integer(), nullable=False),
        sa.Column("old_value", sa.String(100)),
        sa.Column("actual_value", sa.String(100)),
        sa.Column("state", sa.String(30), nullable=False),
        sa.Column("outcome", sa.String(30)),
        sa.Column("processing_id", sa.Uuid()),
        sa.Column("reset_id", sa.Uuid(), unique=True),
        sa.Column(
            "reset_actor_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT")
        ),
        sa.Column("verified_at", sa.DateTime(timezone=True)),
        *[
            sa.Column(
                name,
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            )
            for name in ("created_at", "updated_at", "next_attempt_at")
        ],
        sa.CheckConstraint(
            "(key='HeartbeatInterval' AND value BETWEEN 30 AND 600) OR (key='MeterValueSampleInterval' AND value BETWEEN 5 AND 300)",
            name="ck_configuration_whitelist",
        ),
        sa.CheckConstraint(
            "state IN ('queued','sending','accepted','reboot_required','resetting','verified','needs_review','failed')",
            name="ck_configuration_state",
        ),
    )
    op.create_index(
        "ix_configuration_pending",
        "ocpp_configuration_intents",
        ["state", "next_attempt_at"],
    )
    op.create_index(
        "uq_configuration_active_charger",
        "ocpp_configuration_intents",
        ["charge_point_id"],
        unique=True,
        postgresql_where=sa.text(
            "state IN ('queued','sending','accepted','reboot_required','resetting')"
        ),
    )


def downgrade() -> None:
    op.drop_table("ocpp_configuration_intents")
