"""Append-only remote control requests and outcomes."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "f52c813d7a09"
down_revision = "e41b9027c6a8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ocpp_control_requests",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("actor_email", sa.String(320), nullable=False),
        sa.Column("charge_point_code", sa.String(64), nullable=False),
        sa.Column(
            "actor_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "charge_point_id",
            sa.Uuid(),
            sa.ForeignKey("charge_points.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("transaction_id", sa.Integer()),
        sa.Column("action", sa.String(40), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    for field in ("actor_id", "charge_point_id", "created_at"):
        op.create_index(
            f"ix_ocpp_control_requests_{field}", "ocpp_control_requests", [field]
        )
    op.create_table(
        "ocpp_control_results",
        sa.Column(
            "command_id",
            sa.Uuid(),
            sa.ForeignKey("ocpp_control_requests.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.execute("""CREATE FUNCTION reject_control_audit_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN RAISE EXCEPTION 'control audit is append-only'; END; $$""")
    for table in ("ocpp_control_requests", "ocpp_control_results"):
        op.execute(
            f"CREATE TRIGGER immutable_control_audit BEFORE UPDATE OR DELETE OR TRUNCATE ON {table} FOR EACH STATEMENT EXECUTE FUNCTION reject_control_audit_mutation()"
        )
        op.execute(f"REVOKE UPDATE, DELETE, TRUNCATE ON {table} FROM PUBLIC")


def downgrade() -> None:
    op.drop_table("ocpp_control_results")
    op.drop_table("ocpp_control_requests")
    op.execute("DROP FUNCTION reject_control_audit_mutation()")
