"""Monthly period close/reopen orchestration for S-55."""

import hashlib
import json
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.accounting.models import ReconciliationRun
from src.modules.accounting.period_models import (
    PeriodClose,
    PeriodRevision,
    PeriodSnapshot,
)
from src.modules.accounting.revenue_share import (
    RevenueShareDay,
    calculate_partner_revenue_share,
)

REPORT_TIMEZONE = ZoneInfo("Asia/Ho_Chi_Minh")


class PeriodClosingError(ValueError):
    """Raised when a period cannot be closed or reopened safely."""


def month_date_range(period_start: date) -> tuple[date, date]:
    """Return inclusive calendar-month dates and reject non-month boundaries."""
    if period_start.day != 1:
        raise PeriodClosingError("Kỳ đối soát phải bắt đầu vào ngày đầu tháng")
    if period_start.month == 12:
        next_month = date(period_start.year + 1, 1, 1)
    else:
        next_month = date(period_start.year, period_start.month + 1, 1)
    return period_start, next_month - timedelta(days=1)


def _month_end_exclusive_utc(period_end: date) -> datetime:
    local_boundary = datetime.combine(
        period_end + timedelta(days=1), time.min, tzinfo=REPORT_TIMEZONE
    )
    return local_boundary.astimezone(UTC)


async def _lock_period(db: AsyncSession, period_start: date) -> None:
    lock_key = period_start.year * 100 + period_start.month
    await db.scalar(select(func.pg_advisory_xact_lock(55055, lock_key)))


def _validate_reconciliation_run(
    run: ReconciliationRun,
    period_start: date,
    period_end: date,
) -> None:
    if (
        run.status != "completed"
        or run.period_type != "month"
        or run.date_from != period_start
        or run.date_to != period_end
        or run.station_id is not None
    ):
        raise PeriodClosingError(
            "Cần đợt S-53 hoàn tất cho đúng toàn bộ tháng đối soát"
        )

    if run.cutoff_at.tzinfo is None or run.cutoff_at < _month_end_exclusive_utc(
        period_end
    ):
        raise PeriodClosingError("Mốc chốt S-53 phải sau khi tháng đã kết thúc")

    if (
        run.mismatch_sessions != 0
        or run.missing_data_sessions != 0
        or run.total_sessions != run.matched_sessions + run.mismatch_sessions
    ):
        raise PeriodClosingError("Đợt S-53 còn sai lệch hoặc thiếu dữ liệu")

    for key in ("critical", "warning"):
        value = run.summary_counts.get(key, 0)
        if not isinstance(value, int) or value != 0:
            raise PeriodClosingError(f"Đợt S-53 còn cảnh báo chưa xử lý ({key})")


def _serialize_revenue_share(
    rows: list[RevenueShareDay], period_start: date, period_end: date
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[tuple[UUID, date, UUID | None]] = set()
    for row in rows:
        if not period_start <= row.local_date <= period_end:
            raise PeriodClosingError("S-54 trả dữ liệu doanh thu ngoài tháng đang chốt")
        key = (row.station_id, row.local_date, row.contract_id)
        if key in seen:
            raise PeriodClosingError("S-54 trả dòng doanh thu bị trùng")
        seen.add(key)

        gross_vnd = row.energy_vnd + row.idle_vnd
        if (
            min(
                row.energy_vnd,
                row.idle_vnd,
                row.owner_share_vnd,
                row.partner_share_vnd,
                row.unallocated_vnd,
            )
            < 0
            or row.owner_share_vnd + row.partner_share_vnd + row.unallocated_vnd
            != gross_vnd
        ):
            raise PeriodClosingError("S-54 trả kết quả chia doanh thu không hợp lệ")
        if row.contract_id is not None and (
            row.owner_id is None
            or row.owner_share_bps is None
            or not 0 <= row.owner_share_bps <= 10_000
        ):
            raise PeriodClosingError("S-54 trả hợp đồng chia doanh thu chưa đầy đủ")

        result.append(
            {
                "station_id": str(row.station_id),
                "local_date": row.local_date.isoformat(),
                "contract_id": str(row.contract_id) if row.contract_id else None,
                "owner_id": str(row.owner_id) if row.owner_id else None,
                "owner_share_bps": row.owner_share_bps,
                "energy_vnd": row.energy_vnd,
                "idle_vnd": row.idle_vnd,
                "owner_share_vnd": row.owner_share_vnd,
                "partner_share_vnd": row.partner_share_vnd,
                "unallocated_vnd": row.unallocated_vnd,
            }
        )
    return result


def _build_snapshot_payload(
    run: ReconciliationRun,
    period_start: date,
    period_end: date,
    cutoff_at: datetime,
    revenue_share: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "period": {
            "start": period_start.isoformat(),
            "end": period_end.isoformat(),
            "timezone": "Asia/Ho_Chi_Minh",
        },
        "cutoff_at": cutoff_at.isoformat(),
        "reconciliation": {
            "run_id": str(run.id),
            "cutoff_at": run.cutoff_at.isoformat(),
            "input_hash": run.input_hash,
            "algorithm_version": run.algorithm_version,
            "total_sessions": run.total_sessions,
            "matched_sessions": run.matched_sessions,
            "mismatch_sessions": run.mismatch_sessions,
            "missing_data_sessions": run.missing_data_sessions,
            "total_meter_kwh": str(run.total_meter_kwh),
            "total_billed_kwh": str(run.total_billed_kwh),
            "kwh_discrepancy": str(run.kwh_discrepancy),
            "total_billed_vnd": run.total_billed_vnd,
            "total_recomputed_vnd": run.total_recomputed_vnd,
            "total_debited_vnd": run.total_debited_vnd,
            "money_discrepancy_vnd": run.money_discrepancy_vnd,
            "summary_counts": run.summary_counts,
        },
        "revenue_share": revenue_share,
    }


def _hash_payload(payload: dict[str, Any]) -> str:
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


async def close_period(
    db: AsyncSession,
    *,
    period_start: date,
    reconciliation_run_id: UUID,
    actor_id: UUID | None = None,
) -> PeriodSnapshot:
    """Close a completed calendar month without mutating source financial data.

    The caller owns the transaction and must commit only after this function
    succeeds. S-53 must already contain a clean, full-month reconciliation run.
    S-54 is recalculated for the same local calendar-month dates and copied into
    the immutable snapshot.
    """
    period_start, period_end = month_date_range(period_start)
    if datetime.now(REPORT_TIMEZONE).date() <= period_end:
        raise PeriodClosingError("Chỉ được chốt kỳ sau khi tháng đã kết thúc")

    await _lock_period(db, period_start)
    run = await db.scalar(
        select(ReconciliationRun)
        .where(ReconciliationRun.id == reconciliation_run_id)
        .execution_options(populate_existing=True)
    )
    if run is None:
        raise PeriodClosingError("Không tìm thấy đợt đối soát S-53")
    _validate_reconciliation_run(run, period_start, period_end)

    existing = await db.scalar(
        select(PeriodClose)
        .where(PeriodClose.period_start == period_start)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if existing is not None and existing.status == "closed":
        raise PeriodClosingError("Kỳ đối soát đã được chốt")

    prior_run = await db.scalar(
        select(PeriodSnapshot.id)
        .where(PeriodSnapshot.reconciliation_run_id == reconciliation_run_id)
        .limit(1)
    )
    if prior_run is not None:
        raise PeriodClosingError("Cần đợt S-53 mới cho revision chốt kỳ này")

    revenue_rows = await calculate_partner_revenue_share(
        db,
        date_from=period_start,
        date_to=period_end,
    )
    serialized_revenue = _serialize_revenue_share(
        revenue_rows, period_start, period_end
    )
    cutoff_at = datetime.now(UTC)
    payload = _build_snapshot_payload(
        run,
        period_start,
        period_end,
        cutoff_at,
        serialized_revenue,
    )
    revision = existing.revision + 1 if existing is not None else 1

    if existing is None:
        existing = PeriodClose(
            period_start=period_start,
            period_end=period_end,
            status="closed",
            revision=revision,
        )
        db.add(existing)
        await db.flush()

    snapshot = PeriodSnapshot(
        period_close_id=existing.id,
        revision=revision,
        reconciliation_run_id=run.id,
        closed_by=actor_id,
        cutoff_at=cutoff_at,
        payload=payload,
        snapshot_hash=_hash_payload(payload),
    )
    db.add(snapshot)
    await db.flush()
    if revision > 1:
        existing.status = "closed"
        existing.revision = revision
        await db.flush()
    return snapshot


async def reopen_period(
    db: AsyncSession,
    *,
    period_start: date,
    reason: str,
    actor_id: UUID | None = None,
) -> PeriodRevision:
    """Append a reopen revision; never alter a snapshot, invoice, or ledger row."""
    period_start, _ = month_date_range(period_start)
    normalized_reason = reason.strip()
    if not normalized_reason:
        raise PeriodClosingError("Cần lý do mở lại kỳ đối soát")
    if len(normalized_reason) > 1000:
        raise PeriodClosingError("Lý do mở lại kỳ không được vượt quá 1000 ký tự")

    await _lock_period(db, period_start)
    period = await db.scalar(
        select(PeriodClose)
        .where(PeriodClose.period_start == period_start)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if period is None or period.status != "closed":
        raise PeriodClosingError("Chỉ có thể mở lại kỳ đang ở trạng thái đã chốt")

    previous_snapshot = await db.scalar(
        select(PeriodSnapshot)
        .where(
            PeriodSnapshot.period_close_id == period.id,
            PeriodSnapshot.revision == period.revision,
        )
        .execution_options(populate_existing=True)
    )
    if previous_snapshot is None:
        raise PeriodClosingError("Không tìm thấy snapshot của lần chốt hiện tại")

    revision = PeriodRevision(
        period_close_id=period.id,
        revision=period.revision + 1,
        previous_snapshot_id=previous_snapshot.id,
        reopened_by=actor_id,
        reason=normalized_reason,
    )
    db.add(revision)
    await db.flush()
    period.status = "open"
    period.revision = revision.revision
    await db.flush()
    return revision
