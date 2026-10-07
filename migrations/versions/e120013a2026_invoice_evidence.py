"""invoice_evidence

Revision ID: e120013a2026
Revises: c100011a2026
Create Date: 2026-10-07 22:13:23.680547

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e120013a2026"
down_revision: str | Sequence[str] | None = "c100011a2026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "invoices",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("driver_id", sa.Uuid(), nullable=False),
        sa.Column("station_id", sa.Uuid(), nullable=False),
        sa.Column("total_vnd", sa.BigInteger(), nullable=False),
        sa.Column("rounding_rule", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "btrim(rounding_rule) <> ''", name="ck_invoices_rounding_rule"
        ),
        sa.CheckConstraint("total_vnd >= 0", name="ck_invoices_total"),
        sa.ForeignKeyConstraint(["driver_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["session_id"], ["charging_sessions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["station_id"], ["stations.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id", name="uq_invoices_session"),
    )
    op.create_index(
        "ix_invoices_driver_created",
        "invoices",
        ["driver_id", "created_at"],
        unique=False,
    )
    op.create_table(
        "invoice_lines",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("invoice_id", sa.Uuid(), nullable=False),
        sa.Column("line_type", sa.String(length=20), nullable=False),
        sa.Column("local_date", sa.Date(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("energy_wh", sa.Numeric(precision=24, scale=6), nullable=False),
        sa.Column("rate_vnd", sa.BigInteger(), nullable=False),
        sa.Column("band_label", sa.String(length=100), nullable=False),
        sa.Column("interpolated", sa.Boolean(), nullable=False),
        sa.Column("tariff_id", sa.Uuid(), nullable=False),
        sa.Column("amount_vnd", sa.BigInteger(), nullable=False),
        sa.CheckConstraint("btrim(band_label) <> ''", name="ck_invoice_lines_label"),
        sa.CheckConstraint(
            "line_type <> 'idle' OR energy_wh = 0", name="ck_invoice_lines_idle_energy"
        ),
        sa.CheckConstraint(
            "line_type IN ('energy', 'idle')", name="ck_invoice_lines_type"
        ),
        sa.CheckConstraint(
            "energy_wh >= 0 AND rate_vnd >= 0 AND amount_vnd >= 0",
            name="ck_invoice_lines_nonnegative",
        ),
        sa.CheckConstraint("started_at < ended_at", name="ck_invoice_lines_interval"),
        sa.ForeignKeyConstraint(["invoice_id"], ["invoices.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tariff_id"], ["tariffs.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_invoice_lines_invoice", "invoice_lines", ["invoice_id"], unique=False
    )
    op.add_column(
        "charging_sessions",
        sa.Column("settlement_completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "charging_sessions",
        sa.Column("settlement_reason", sa.String(length=20), nullable=True),
    )
    op.create_check_constraint(
        "ck_charging_sessions_settlement",
        "charging_sessions",
        "(settlement_completed_at IS NULL AND settlement_reason IS NULL) OR "
        "(settlement_completed_at IS NOT NULL AND settlement_reason IS NOT NULL "
        "AND settlement_reason IN ('debited', 'zero_invoice', 'legacy_exempt'))",
    )
    op.execute("""CREATE FUNCTION reject_invoice_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN RAISE EXCEPTION 'invoice evidence is append-only'; END; $$""")
    for table in ("invoices", "invoice_lines"):
        op.execute(
            f"CREATE TRIGGER immutable_{table} BEFORE UPDATE OR DELETE OR TRUNCATE ON {table} FOR EACH STATEMENT EXECUTE FUNCTION reject_invoice_mutation()"
        )
        op.execute(f"REVOKE UPDATE, DELETE, TRUNCATE ON {table} FROM PUBLIC")


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(
        "ck_charging_sessions_settlement", "charging_sessions", type_="check"
    )
    op.drop_column("charging_sessions", "settlement_reason")
    op.drop_column("charging_sessions", "settlement_completed_at")
    op.drop_index("ix_invoice_lines_invoice", table_name="invoice_lines")
    op.drop_table("invoice_lines")
    op.drop_index("ix_invoices_driver_created", table_name="invoices")
    op.drop_table("invoices")
    op.execute("DROP FUNCTION reject_invoice_mutation()")
