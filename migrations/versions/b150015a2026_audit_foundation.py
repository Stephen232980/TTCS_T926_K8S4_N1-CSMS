"""T-57 A: general audit index; business integrations follow separately."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "b150015a2026"
down_revision = "f130014a2026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "actor_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT")
        ),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("object_type", sa.String(100), nullable=False),
        sa.Column("object_id", sa.Text(), nullable=False),
        sa.Column(
            "data",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("permission", sa.String(100)),
        sa.Column("actor_roles", postgresql.JSONB()),
        sa.CheckConstraint(
            "btrim(action) <> '' AND btrim(object_type) <> '' AND btrim(object_id) <> ''",
            name="ck_audit_logs_identifiers",
        ),
        sa.CheckConstraint("jsonb_typeof(data) = 'object'", name="ck_audit_logs_data"),
        sa.CheckConstraint(
            "actor_roles IS NULL OR jsonb_typeof(actor_roles) = 'array'",
            name="ck_audit_logs_roles",
        ),
    )
    op.create_index(
        "ix_audit_logs_occurred_at_desc", "audit_logs", [sa.text("occurred_at DESC")]
    )
    op.create_index("ix_audit_logs_object", "audit_logs", ["object_type", "object_id"])
    op.execute("""CREATE FUNCTION reject_audit_log_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN RAISE EXCEPTION 'audit log is append-only'; END; $$""")
    op.execute("""CREATE TRIGGER immutable_audit_logs
        BEFORE UPDATE OR DELETE OR TRUNCATE ON audit_logs
        FOR EACH STATEMENT EXECUTE FUNCTION reject_audit_log_mutation()""")
    op.execute("REVOKE ALL ON TABLE audit_logs FROM PUBLIC")


def downgrade() -> None:
    op.drop_table("audit_logs")
    op.execute("DROP FUNCTION reject_audit_log_mutation()")
