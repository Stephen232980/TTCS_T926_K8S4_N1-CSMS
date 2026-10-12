"""T-102: Backfill legacy_exempt for invoices created before cutoff without debit ledger.

Revision ID: 4db8d8987c3a
Revises: d180018a2026
Create Date: 2026-10-11 22:53:55
"""

import logging
import os
from collections.abc import Sequence
from datetime import UTC, datetime

from alembic import context, op
from sqlalchemy.sql import text

from src.config import settings

logger = logging.getLogger("alembic.runtime.migration")

# revision identifiers, used by Alembic.
revision: str = "4db8d8987c3a"
down_revision: str | Sequence[str] | None = "d180018a2026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def get_cutoff_iso() -> str | None:
    """Retrieve cutoff timestamp from CLI x-arguments, environment, or settings."""
    x_args = context.get_x_argument(as_dictionary=True)
    val = (
        x_args.get("legacy_cutoff")
        or os.environ.get("LEGACY_SETTLEMENT_CUTOFF")
        or settings.legacy_settlement_cutoff
    )
    if val and val.strip():
        return val.strip()
    return None


def upgrade() -> None:
    """Backfill legacy_exempt for charging sessions whose invoices were created before cutoff

    and do not have a charging_debit entry in wallet_ledger.
    """
    cutoff_str = get_cutoff_iso()
    if not cutoff_str:
        raise ValueError("T-102 requires an approved LEGACY_SETTLEMENT_CUTOFF")

    cutoff_dt = datetime.fromisoformat(cutoff_str)
    if cutoff_dt.tzinfo is None:
        raise ValueError("T-102 cutoff must include a timezone")
    cutoff_dt = cutoff_dt.astimezone(UTC)

    conn = op.get_bind()
    params = {"cutoff": cutoff_dt, "completed_at": datetime.now(UTC)}
    # A suspicious ledger is never treated as an exemption or a completed debit.
    reviewed = conn.execute(
        text(
            """
            UPDATE charging_sessions cs
            SET review_reasons = CASE
                WHEN review_reasons @> '["settlement_ledger_mismatch"]'::jsonb
                THEN review_reasons
                ELSE review_reasons || '["settlement_ledger_mismatch"]'::jsonb END
            FROM invoices inv
            WHERE cs.id = inv.session_id AND cs.settlement_completed_at IS NULL
              AND EXISTS (
                  SELECT 1 FROM wallet_ledger wl
                  LEFT JOIN wallets w ON w.id = wl.wallet_id
                  WHERE wl.reference_id = cs.id::text
                    AND (wl.entry_type = 'charging_debit'
                         OR wl.reference_type = 'charging_session')
                    AND (wl.entry_type <> 'charging_debit'
                         OR wl.reference_type <> 'charging_session'
                         OR w.driver_id <> inv.driver_id
                         OR wl.amount_vnd <> -inv.total_vnd OR inv.total_vnd = 0)
              )
            """
        )
    ).rowcount
    debited = conn.execute(
        text(
            """
            UPDATE charging_sessions cs
            SET settlement_completed_at = :completed_at, settlement_reason = 'debited'
            FROM invoices inv
            WHERE cs.id = inv.session_id AND cs.settlement_completed_at IS NULL
              AND cs.review_reasons = '[]'::jsonb AND inv.total_vnd > 0
              AND EXISTS (
                  SELECT 1 FROM wallet_ledger wl JOIN wallets w ON w.id = wl.wallet_id
                  WHERE wl.entry_type = 'charging_debit'
                    AND wl.reference_type = 'charging_session'
                    AND wl.reference_id = cs.id::text
                    AND w.driver_id = inv.driver_id AND wl.amount_vnd = -inv.total_vnd
              )
            """
        ),
        params,
    ).rowcount
    result = conn.execute(
        text(
            """
            UPDATE charging_sessions cs
            SET settlement_completed_at = :completed_at,
                settlement_reason = 'legacy_exempt'
            FROM invoices inv
            WHERE cs.id = inv.session_id
              AND inv.created_at < :cutoff
              AND cs.settlement_completed_at IS NULL
              AND cs.review_reasons = '[]'::jsonb
              AND NOT EXISTS (
                  SELECT 1 FROM wallet_ledger wl
                  WHERE (wl.entry_type = 'charging_debit'
                         OR wl.reference_type = 'charging_session')
                    AND wl.reference_id = cs.id::text
              )
            """
        ),
        params,
    )
    affected_count = result.rowcount
    logger.info(
        "T-102 migration audit: database=%s cutoff=%s legacy_exempt=%s debited=%s needs_review=%s",
        conn.execute(text("SELECT current_database()")).scalar_one(),
        cutoff_dt.isoformat(),
        affected_count,
        debited,
        reviewed,
    )


def downgrade() -> None:
    """Revert legacy_exempt mark for sessions that were exempted."""
    op.execute(
        text(
            """
            UPDATE charging_sessions
            SET settlement_completed_at = NULL,
                settlement_reason = NULL
            WHERE settlement_reason = 'legacy_exempt'
            """
        )
    )
