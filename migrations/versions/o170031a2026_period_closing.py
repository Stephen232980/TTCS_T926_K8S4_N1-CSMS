"""S-55 monthly reconciliation period closing and immutable snapshots."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "o170031a2026"
down_revision = "n170030a2026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "period_closes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "EXTRACT(DAY FROM period_start) = 1",
            name="ck_period_closes_month_start",
        ),
        sa.CheckConstraint(
            "period_end >= period_start", name="ck_period_closes_date_range"
        ),
        sa.CheckConstraint(
            "status IN ('open', 'closed')", name="ck_period_closes_status"
        ),
        sa.CheckConstraint("revision >= 1", name="ck_period_closes_revision"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("period_start", name="uq_period_closes_period_start"),
    )
    op.create_index(
        "ix_period_closes_status", "period_closes", ["status", "period_start"]
    )

    op.create_table(
        "period_snapshots",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("period_close_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("reconciliation_run_id", sa.Uuid(), nullable=False),
        sa.Column("closed_by", sa.Uuid(), nullable=True),
        sa.Column("cutoff_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("snapshot_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("revision >= 1", name="ck_period_snapshots_revision"),
        sa.CheckConstraint(
            "length(snapshot_hash) = 64", name="ck_period_snapshots_hash_length"
        ),
        sa.ForeignKeyConstraint(
            ["period_close_id"], ["period_closes.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["reconciliation_run_id"],
            ["reconciliation_runs.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["closed_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "period_close_id",
            "revision",
            name="uq_period_snapshots_close_revision",
        ),
        sa.UniqueConstraint(
            "reconciliation_run_id",
            name="uq_period_snapshots_reconciliation_run",
        ),
    )
    op.create_index(
        "ix_period_snapshots_close_id",
        "period_snapshots",
        ["period_close_id", "revision"],
    )

    op.create_table(
        "period_revisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("period_close_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("previous_snapshot_id", sa.Uuid(), nullable=False),
        sa.Column("reopened_by", sa.Uuid(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "reopened_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("revision >= 2", name="ck_period_revisions_revision"),
        sa.CheckConstraint("btrim(reason) <> ''", name="ck_period_revisions_reason"),
        sa.ForeignKeyConstraint(
            ["period_close_id"], ["period_closes.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["previous_snapshot_id"],
            ["period_snapshots.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["reopened_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "period_close_id",
            "revision",
            name="uq_period_revisions_close_revision",
        ),
    )
    op.create_index(
        "ix_period_revisions_close_id",
        "period_revisions",
        ["period_close_id", "revision"],
    )

    op.execute(
        """
        CREATE FUNCTION reject_period_evidence_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION '% is append-only', TG_TABLE_NAME;
        END;
        $$
        """
    )
    for table in ("period_snapshots", "period_revisions"):
        op.execute(
            f"CREATE TRIGGER immutable_{table} "
            f"BEFORE UPDATE OR DELETE OR TRUNCATE ON {table} "
            "FOR EACH STATEMENT EXECUTE FUNCTION "
            "reject_period_evidence_mutation()"
        )
        op.execute(f"REVOKE UPDATE, DELETE, TRUNCATE ON {table} FROM PUBLIC")

    op.execute(
        """
        CREATE FUNCTION guard_period_snapshot_insert()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
            current_status text;
            current_revision integer;
        BEGIN
            SELECT status, revision INTO current_status, current_revision
            FROM period_closes WHERE id = NEW.period_close_id FOR UPDATE;
            IF NOT FOUND OR NOT (
                (current_status = 'closed' AND current_revision = NEW.revision)
                OR
                (current_status = 'open' AND current_revision + 1 = NEW.revision)
            ) THEN
                RAISE EXCEPTION 'snapshot does not match the current period revision';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER guard_period_snapshot
        BEFORE INSERT ON period_snapshots
        FOR EACH ROW EXECUTE FUNCTION guard_period_snapshot_insert()
        """
    )
    op.execute(
        """
        CREATE FUNCTION guard_period_revision_insert()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
            current_status text;
            current_revision integer;
        BEGIN
            SELECT status, revision INTO current_status, current_revision
            FROM period_closes WHERE id = NEW.period_close_id FOR UPDATE;
            IF NOT FOUND OR current_status <> 'closed'
               OR NEW.revision <> current_revision + 1
               OR NOT EXISTS (
                   SELECT 1 FROM period_snapshots
                   WHERE id = NEW.previous_snapshot_id
                     AND period_close_id = NEW.period_close_id
                     AND revision = current_revision
               ) THEN
                RAISE EXCEPTION 'revision does not reopen the current snapshot';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER guard_period_revision
        BEFORE INSERT ON period_revisions
        FOR EACH ROW EXECUTE FUNCTION guard_period_revision_insert()
        """
    )
    op.execute(
        """
        CREATE FUNCTION verify_period_history_consistency()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_TABLE_NAME = 'period_closes' THEN
                IF NEW.status = 'closed' AND NOT EXISTS (
                    SELECT 1 FROM period_snapshots
                    WHERE period_close_id = NEW.id AND revision = NEW.revision
                ) THEN
                    RAISE EXCEPTION 'closed period requires its immutable snapshot';
                END IF;
            ELSIF NOT EXISTS (
                SELECT 1 FROM period_closes
                WHERE id = NEW.period_close_id
                  AND status = 'open'
                  AND revision = NEW.revision
            ) THEN
                RAISE EXCEPTION 'reopen revision requires an open period state';
            END IF;
            RETURN NULL;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER period_close_snapshot_required
        AFTER INSERT OR UPDATE ON period_closes
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION verify_period_history_consistency()
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER period_revision_state_required
        AFTER INSERT ON period_revisions
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION verify_period_history_consistency()
        """
    )
    op.execute(
        """
        CREATE FUNCTION enforce_period_close_transition()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'INSERT' THEN
                IF NEW.status <> 'closed' OR NEW.revision <> 1 THEN
                    RAISE EXCEPTION 'a period must start with its first close';
                END IF;
                RETURN NEW;
            END IF;
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'period close history cannot be deleted';
            END IF;
            IF NEW.id IS DISTINCT FROM OLD.id
               OR NEW.period_start IS DISTINCT FROM OLD.period_start
               OR NEW.period_end IS DISTINCT FROM OLD.period_end
               OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
                RAISE EXCEPTION 'period close identity is immutable';
            END IF;
            IF NEW.revision <> OLD.revision + 1
               OR NOT (
                   (OLD.status = 'closed' AND NEW.status = 'open')
                   OR (OLD.status = 'open' AND NEW.status = 'closed')
               ) THEN
                RAISE EXCEPTION 'invalid period close state transition';
            END IF;
            IF OLD.status = 'closed' AND NOT EXISTS (
                SELECT 1 FROM period_revisions
                WHERE period_close_id = OLD.id
                  AND revision = NEW.revision
            ) THEN
                RAISE EXCEPTION 'reopen transition requires an appended revision';
            END IF;
            IF OLD.status = 'open' AND NOT EXISTS (
                SELECT 1 FROM period_snapshots
                WHERE period_close_id = OLD.id
                  AND revision = NEW.revision
            ) THEN
                RAISE EXCEPTION 'close transition requires an immutable snapshot';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER guarded_period_close_transition
        BEFORE INSERT OR UPDATE OR DELETE ON period_closes
        FOR EACH ROW EXECUTE FUNCTION enforce_period_close_transition()
        """
    )
    op.execute(
        """
        CREATE FUNCTION reject_period_close_truncate()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'period close history cannot be truncated';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER immutable_period_closes
        BEFORE TRUNCATE ON period_closes
        FOR EACH STATEMENT EXECUTE FUNCTION reject_period_close_truncate()
        """
    )
    op.execute("REVOKE DELETE, TRUNCATE ON period_closes FROM PUBLIC")


def downgrade() -> None:
    has_history = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT EXISTS (SELECT 1 FROM period_closes) "
                "OR EXISTS (SELECT 1 FROM period_snapshots) "
                "OR EXISTS (SELECT 1 FROM period_revisions)"
            )
        )
        .scalar_one()
    )
    if has_history:
        raise RuntimeError(
            "S-55 period history exists; downgrade requires an explicit recovery plan"
        )

    op.execute("DROP TRIGGER immutable_period_closes ON period_closes")
    op.execute("DROP TRIGGER guarded_period_close_transition ON period_closes")
    op.execute("DROP TRIGGER period_close_snapshot_required ON period_closes")
    op.execute("DROP TRIGGER period_revision_state_required ON period_revisions")
    op.execute("DROP TRIGGER guard_period_revision ON period_revisions")
    op.execute("DROP TRIGGER guard_period_snapshot ON period_snapshots")
    op.execute("DROP FUNCTION reject_period_close_truncate()")
    op.execute("DROP FUNCTION enforce_period_close_transition()")
    op.execute("DROP FUNCTION verify_period_history_consistency()")
    op.execute("DROP FUNCTION guard_period_revision_insert()")
    op.execute("DROP FUNCTION guard_period_snapshot_insert()")
    op.execute("DROP FUNCTION reject_period_evidence_mutation()")
    op.drop_index("ix_period_revisions_close_id", table_name="period_revisions")
    op.drop_table("period_revisions")
    op.drop_index("ix_period_snapshots_close_id", table_name="period_snapshots")
    op.drop_table("period_snapshots")
    op.drop_index("ix_period_closes_status", table_name="period_closes")
    op.drop_table("period_closes")
