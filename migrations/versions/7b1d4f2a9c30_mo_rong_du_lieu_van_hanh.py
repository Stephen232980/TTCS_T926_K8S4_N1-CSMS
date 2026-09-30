"""mo rong du lieu van hanh

Revision ID: 7b1d4f2a9c30
Revises: ecbbbbc04358
Create Date: 2026-09-30 18:15:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "7b1d4f2a9c30"
down_revision: str | Sequence[str] | None = "ecbbbbc04358"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "status", sa.String(length=30), server_default="active", nullable=False
        ),
    )
    op.create_check_constraint(
        "ck_users_status",
        "users",
        "status IN ('active', 'suspended', 'deactivated', "
        "'pending_deletion', 'anonymized')",
    )
    op.create_index(
        "uq_users_email_ci",
        "users",
        [sa.text("lower(email)")],
        unique=True,
    )

    op.add_column(
        "sessions",
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "sessions",
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.add_column(
        "sessions",
        sa.Column("ip_address", sa.String(length=45), nullable=True),
    )
    op.add_column(
        "sessions",
        sa.Column("user_agent", sa.String(length=512), nullable=True),
    )

    op.drop_constraint("ck_stations_status", "stations", type_="check")
    op.create_check_constraint(
        "ck_stations_status",
        "stations",
        "status IN ('inactive', 'active', 'suspended', 'blocked')",
    )
    op.add_column(
        "stations",
        sa.Column(
            "timezone",
            sa.String(length=64),
            server_default="Asia/Ho_Chi_Minh",
            nullable=False,
        ),
    )
    op.add_column(
        "stations",
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.drop_constraint(
        "charge_points_station_id_fkey",
        "charge_points",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "charge_points_station_id_fkey",
        "charge_points",
        "stations",
        ["station_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.add_column(
        "charge_points",
        sa.Column("vendor", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "charge_points",
        sa.Column("model", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "charge_points",
        sa.Column("firmware_version", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "charge_points",
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "charge_points",
        sa.Column("last_boot_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "charge_points",
        sa.Column(
            "status_updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.add_column(
        "charge_points",
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "charge_points",
        sa.Column("code_locked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "uq_charge_points_code_ci",
        "charge_points",
        [sa.text("lower(code)")],
        unique=True,
    )
    op.execute(
        """
        CREATE FUNCTION prevent_locked_charge_point_code_update()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF OLD.code_locked_at IS NOT NULL
               AND (
                   NEW.code IS DISTINCT FROM OLD.code
                   OR NEW.code_locked_at IS DISTINCT FROM OLD.code_locked_at
               ) THEN
                RAISE EXCEPTION USING
                    ERRCODE = '23514',
                    CONSTRAINT = 'ck_charge_points_code_locked',
                    MESSAGE = 'charge point code is locked after charging';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_charge_points_code_locked
        BEFORE UPDATE OF code, code_locked_at ON charge_points
        FOR EACH ROW
        EXECUTE FUNCTION prevent_locked_charge_point_code_update()
        """
    )

    op.drop_constraint(
        "connectors_charge_point_id_fkey",
        "connectors",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "connectors_charge_point_id_fkey",
        "connectors",
        "charge_points",
        ["charge_point_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.add_column(
        "connectors",
        sa.Column("raw_ocpp_status", sa.String(length=50), nullable=True),
    )
    op.add_column(
        "connectors",
        sa.Column(
            "status_updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.add_column(
        "connectors",
        sa.Column("connector_type", sa.String(length=50), nullable=True),
    )
    op.add_column(
        "connectors",
        sa.Column("max_power_kw", sa.Numeric(precision=8, scale=3), nullable=True),
    )
    op.add_column(
        "connectors",
        sa.Column("current_type", sa.String(length=20), nullable=True),
    )
    op.add_column(
        "connectors",
        sa.Column("voltage", sa.Numeric(precision=8, scale=2), nullable=True),
    )
    op.add_column(
        "connectors",
        sa.Column("amperage", sa.Numeric(precision=8, scale=2), nullable=True),
    )
    op.add_column(
        "connectors",
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        "ck_connectors_max_power_kw_positive",
        "connectors",
        "max_power_kw IS NULL OR max_power_kw > 0",
    )
    op.create_check_constraint(
        "ck_connectors_voltage_positive",
        "connectors",
        "voltage IS NULL OR voltage > 0",
    )
    op.create_check_constraint(
        "ck_connectors_amperage_positive",
        "connectors",
        "amperage IS NULL OR amperage > 0",
    )

    op.create_table(
        "connector_errors",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("connector_id", sa.Uuid(), nullable=False),
        sa.Column("error_code", sa.String(length=100), nullable=False),
        sa.Column("vendor_error_code", sa.String(length=255), nullable=True),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("details", sa.String(length=1000), nullable=True),
        sa.ForeignKeyConstraint(
            ["connector_id"],
            ["connectors.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_connector_errors_connector_id_occurred_at",
        "connector_errors",
        ["connector_id", "occurred_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_connector_errors_connector_id_occurred_at",
        table_name="connector_errors",
    )
    op.drop_table("connector_errors")

    op.drop_constraint(
        "ck_connectors_amperage_positive",
        "connectors",
        type_="check",
    )
    op.drop_constraint(
        "ck_connectors_voltage_positive",
        "connectors",
        type_="check",
    )
    op.drop_constraint(
        "ck_connectors_max_power_kw_positive",
        "connectors",
        type_="check",
    )
    op.drop_column("connectors", "archived_at")
    op.drop_column("connectors", "amperage")
    op.drop_column("connectors", "voltage")
    op.drop_column("connectors", "current_type")
    op.drop_column("connectors", "max_power_kw")
    op.drop_column("connectors", "connector_type")
    op.drop_column("connectors", "status_updated_at")
    op.drop_column("connectors", "raw_ocpp_status")
    op.drop_constraint(
        "connectors_charge_point_id_fkey",
        "connectors",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "connectors_charge_point_id_fkey",
        "connectors",
        "charge_points",
        ["charge_point_id"],
        ["id"],
        ondelete="CASCADE",
    )

    op.execute("DROP TRIGGER IF EXISTS trg_charge_points_code_locked ON charge_points")
    op.execute("DROP FUNCTION IF EXISTS prevent_locked_charge_point_code_update()")
    op.drop_index("uq_charge_points_code_ci", table_name="charge_points")
    op.execute("ALTER TABLE charge_points DROP COLUMN IF EXISTS code_locked_at")
    op.drop_column("charge_points", "archived_at")
    op.drop_column("charge_points", "status_updated_at")
    op.drop_column("charge_points", "last_boot_at")
    op.drop_column("charge_points", "last_seen_at")
    op.drop_column("charge_points", "firmware_version")
    op.drop_column("charge_points", "model")
    op.drop_column("charge_points", "vendor")
    op.drop_constraint(
        "charge_points_station_id_fkey",
        "charge_points",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "charge_points_station_id_fkey",
        "charge_points",
        "stations",
        ["station_id"],
        ["id"],
        ondelete="CASCADE",
    )

    op.drop_column("stations", "archived_at")
    op.drop_column("stations", "timezone")
    op.drop_constraint("ck_stations_status", "stations", type_="check")
    op.create_check_constraint(
        "ck_stations_status",
        "stations",
        "status IN ('inactive', 'active')",
    )

    op.drop_column("sessions", "user_agent")
    op.drop_column("sessions", "ip_address")
    op.drop_column("sessions", "last_seen_at")
    op.drop_column("sessions", "revoked_at")

    op.drop_index("uq_users_email_ci", table_name="users")
    op.drop_constraint("ck_users_status", "users", type_="check")
    op.drop_column("users", "status")
