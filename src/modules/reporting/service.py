from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from math import ceil
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import String, and_, case, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.billing.models import Invoice, InvoiceLine
from src.modules.charging.models import ChargingSession
from src.modules.reporting.schemas import (
    ChargePointRevenueItem,
    DailyRevenueItem,
    PaginationMeta,
    PeriodType,
    RevenueReportQuery,
    RevenueReportResponse,
    RevenueSummary,
)
from src.modules.stations.models import ChargePoint, Station
from src.modules.wallet.models import WalletLedger
from src.platform.csv_export import build_csv_streaming_response

REPORT_TIMEZONE = ZoneInfo("Asia/Ho_Chi_Minh")


@dataclass
class _CPAccumulator:
    station_id: UUID
    station_name: str
    charge_point_id: UUID
    charge_point_code: str
    sessions_count: int = 0
    energy_wh: Decimal = field(default_factory=lambda: Decimal(0))
    energy_amount_vnd: int = 0
    idle_amount_vnd: int = 0
    total_invoice_vnd: int = 0
    debited_vnd: int = 0
    awaiting_settlement_vnd: int = 0
    unbilled_sessions: int = 0
    unbilled_operating_kwh: Decimal = field(default_factory=lambda: Decimal(0))


@dataclass
class _DailyAccumulator:
    date: str
    sessions_count: int = 0
    kwh: Decimal = field(default_factory=lambda: Decimal(0))
    invoice_vnd: int = 0
    debited_vnd: int = 0


def resolve_report_range(
    period: PeriodType,
    date_from: date | None = None,
    date_to: date | None = None,
    now_dt: datetime | None = None,
) -> tuple[datetime, datetime]:
    """Resolve report start and end datetimes in Asia/Ho_Chi_Minh timezone."""
    now_local = (now_dt or datetime.now(UTC)).astimezone(REPORT_TIMEZONE)
    today = now_local.date()

    if period == "day":
        target_date = date_from or today
        start_dt = datetime.combine(target_date, time.min, REPORT_TIMEZONE)
        end_dt = start_dt + timedelta(days=1)
    elif period == "week":
        ref_date = date_from or today
        monday = ref_date - timedelta(days=ref_date.weekday())
        start_dt = datetime.combine(monday, time.min, REPORT_TIMEZONE)
        end_dt = start_dt + timedelta(days=7)
    elif period == "month":
        ref_date = date_from or today
        first_day = date(ref_date.year, ref_date.month, 1)
        if first_day.month == 12:
            next_month = date(first_day.year + 1, 1, 1)
        else:
            next_month = date(first_day.year, first_day.month + 1, 1)
        start_dt = datetime.combine(first_day, time.min, REPORT_TIMEZONE)
        end_dt = datetime.combine(next_month, time.min, REPORT_TIMEZONE)
    else:  # custom
        start_d = date_from or today
        end_d = date_to or start_d
        start_dt = datetime.combine(start_d, time.min, REPORT_TIMEZONE)
        end_dt = datetime.combine(end_d + timedelta(days=1), time.min, REPORT_TIMEZONE)

    return start_dt, end_dt


REVENUE_CSV_HEADERS: list[str] = [
    "period_from",
    "period_to",
    "timezone",
    "station_id",
    "station_name",
    "charge_point_id",
    "charge_point_code",
    "sessions",
    "energy_kwh",
    "energy_vnd",
    "idle_vnd",
    "invoice_total_vnd",
    "debited_vnd",
]


async def _compute_revenue_data(
    db: AsyncSession,
    query: RevenueReportQuery,
    owner_id: UUID | None = None,
) -> tuple[
    datetime,
    datetime,
    list[ChargePointRevenueItem],
    RevenueSummary,
    list[DailyRevenueItem],
]:
    start_dt, end_dt = resolve_report_range(
        query.period, query.date_from, query.date_to
    )

    if owner_id is not None and query.station_id is not None:
        station_owner = await db.scalar(
            select(Station.owner_id).where(Station.id == query.station_id)
        )
        if station_owner is not None and station_owner != owner_id:
            raise HTTPException(
                status_code=403,
                detail="Không có quyền truy cập trạm sạc này",
            )

    # 1. Subquery aggregating InvoiceLine metrics per invoice to prevent duplicates
    line_subq = (
        select(
            InvoiceLine.invoice_id,
            func.coalesce(
                func.sum(
                    case(
                        (InvoiceLine.line_type == "energy", InvoiceLine.energy_wh),
                        else_=0,
                    )
                ),
                0,
            ).label("energy_wh"),
            func.coalesce(
                func.sum(
                    case(
                        (InvoiceLine.line_type == "energy", InvoiceLine.amount_vnd),
                        else_=0,
                    )
                ),
                0,
            ).label("energy_amount_vnd"),
            func.coalesce(
                func.sum(
                    case(
                        (InvoiceLine.line_type == "idle", InvoiceLine.amount_vnd),
                        else_=0,
                    )
                ),
                0,
            ).label("idle_amount_vnd"),
        )
        .group_by(InvoiceLine.invoice_id)
        .subquery("line_agg")
    )

    # 2. Subquery aggregating WalletLedger charging_debit per session
    ledger_subq = (
        select(
            WalletLedger.reference_id,
            func.coalesce(
                func.sum(
                    case(
                        (
                            and_(
                                WalletLedger.entry_type == "charging_debit",
                                WalletLedger.amount_vnd < 0,
                            ),
                            -WalletLedger.amount_vnd,
                        ),
                        else_=0,
                    )
                ),
                0,
            ).label("debited_vnd"),
        )
        .where(WalletLedger.entry_type == "charging_debit")
        .group_by(WalletLedger.reference_id)
        .subquery("ledger_agg")
    )

    # 3. Main invoiced query within [start_dt, end_dt)
    invoiced_query = (
        select(
            Invoice.id.label("invoice_id"),
            Invoice.session_id,
            Invoice.created_at.label("invoice_created_at"),
            Invoice.total_vnd.label("invoice_total_vnd"),
            Station.id.label("station_id"),
            Station.name.label("station_name"),
            ChargePoint.id.label("charge_point_id"),
            ChargePoint.code.label("charge_point_code"),
            func.coalesce(line_subq.c.energy_wh, 0).label("energy_wh"),
            func.coalesce(line_subq.c.energy_amount_vnd, 0).label("energy_amount_vnd"),
            func.coalesce(line_subq.c.idle_amount_vnd, 0).label("idle_amount_vnd"),
            func.coalesce(ledger_subq.c.debited_vnd, 0).label("debited_vnd"),
        )
        .join(ChargingSession, ChargingSession.id == Invoice.session_id)
        .join(ChargePoint, ChargePoint.id == ChargingSession.charge_point_id)
        .join(Station, Station.id == ChargePoint.station_id)
        .outerjoin(line_subq, line_subq.c.invoice_id == Invoice.id)
        .outerjoin(
            ledger_subq,
            ledger_subq.c.reference_id == cast(ChargingSession.id, String),
        )
        .where(
            Invoice.created_at >= start_dt,
            Invoice.created_at < end_dt,
        )
    )

    if owner_id is not None:
        invoiced_query = invoiced_query.where(Station.owner_id == owner_id)
    if query.station_id is not None:
        invoiced_query = invoiced_query.where(Station.id == query.station_id)
    if query.charge_point_id is not None:
        invoiced_query = invoiced_query.where(ChargePoint.id == query.charge_point_id)

    invoiced_rows = (await db.execute(invoiced_query)).all()

    # 3. Query unbilled operating sessions within [start_dt, end_dt) (AC-5)
    unbilled_query = (
        select(
            ChargingSession.id.label("session_id"),
            ChargingSession.energy_kwh,
            Station.id.label("station_id"),
            Station.name.label("station_name"),
            ChargePoint.id.label("charge_point_id"),
            ChargePoint.code.label("charge_point_code"),
        )
        .join(ChargePoint, ChargePoint.id == ChargingSession.charge_point_id)
        .join(Station, Station.id == ChargePoint.station_id)
        .outerjoin(Invoice, Invoice.session_id == ChargingSession.id)
        .where(
            ChargingSession.ended_at.is_not(None),
            ChargingSession.ended_at >= start_dt,
            ChargingSession.ended_at < end_dt,
            Invoice.id.is_(None),
        )
    )

    if owner_id is not None:
        unbilled_query = unbilled_query.where(Station.owner_id == owner_id)
    if query.station_id is not None:
        unbilled_query = unbilled_query.where(Station.id == query.station_id)
    if query.charge_point_id is not None:
        unbilled_query = unbilled_query.where(ChargePoint.id == query.charge_point_id)

    unbilled_rows = (await db.execute(unbilled_query)).all()

    # 4. Aggregations
    # Accumulate by charge point
    cp_map: dict[UUID, _CPAccumulator] = {}

    total_invoiced_sessions = len(invoiced_rows)
    total_energy_wh = Decimal(0)
    total_energy_amount_vnd = 0
    total_idle_amount_vnd = 0
    total_invoice_vnd = 0
    total_debited_vnd = 0
    total_awaiting_settlement_vnd = 0

    # Daily timeline map (keyed by "YYYY-MM-DD")
    daily_map: dict[str, _DailyAccumulator] = {}
    curr_d = start_dt.date()
    end_d = end_dt.date()
    while curr_d < end_d:
        d_str = curr_d.isoformat()
        daily_map[d_str] = _DailyAccumulator(date=d_str)
        curr_d += timedelta(days=1)

    for row in invoiced_rows:
        inv_total = int(row.invoice_total_vnd)
        debited = int(row.debited_vnd)
        awaiting = max(0, inv_total - debited)
        energy_wh = Decimal(str(row.energy_wh))
        energy_amt = int(row.energy_amount_vnd)
        idle_amt = int(row.idle_amount_vnd)

        total_energy_wh += energy_wh
        total_energy_amount_vnd += energy_amt
        total_idle_amount_vnd += idle_amt
        total_invoice_vnd += inv_total
        total_debited_vnd += debited
        total_awaiting_settlement_vnd += awaiting

        cp_id = row.charge_point_id
        if cp_id not in cp_map:
            cp_map[cp_id] = _CPAccumulator(
                station_id=row.station_id,
                station_name=row.station_name,
                charge_point_id=cp_id,
                charge_point_code=row.charge_point_code,
            )

        item = cp_map[cp_id]
        item.sessions_count += 1
        item.energy_wh += energy_wh
        item.energy_amount_vnd += energy_amt
        item.idle_amount_vnd += idle_amt
        item.total_invoice_vnd += inv_total
        item.debited_vnd += debited
        item.awaiting_settlement_vnd += awaiting

        # Timeline aggregate
        inv_created = row.invoice_created_at.astimezone(REPORT_TIMEZONE)
        d_str = inv_created.date().isoformat()
        if d_str in daily_map:
            d_entry = daily_map[d_str]
            d_entry.sessions_count += 1
            d_entry.kwh += energy_wh / Decimal(1000)
            d_entry.invoice_vnd += inv_total
            d_entry.debited_vnd += debited

    # Unbilled aggregation
    total_unbilled_sessions = len(unbilled_rows)
    total_unbilled_kwh = Decimal(0)
    for ub in unbilled_rows:
        ub_kwh = (
            Decimal(str(ub.energy_kwh)) if ub.energy_kwh is not None else Decimal(0)
        )
        total_unbilled_kwh += ub_kwh

        cp_id = ub.charge_point_id
        if cp_id not in cp_map:
            cp_map[cp_id] = _CPAccumulator(
                station_id=ub.station_id,
                station_name=ub.station_name,
                charge_point_id=cp_id,
                charge_point_code=ub.charge_point_code,
            )
        item = cp_map[cp_id]
        item.unbilled_sessions += 1
        item.unbilled_operating_kwh += ub_kwh

    # Format charge point list
    cp_list: list[ChargePointRevenueItem] = []
    for item in cp_map.values():
        kwh = round(item.energy_wh / Decimal(1000), 4)
        unbilled_kwh = round(item.unbilled_operating_kwh, 4)
        cp_list.append(
            ChargePointRevenueItem(
                station_id=item.station_id,
                station_name=item.station_name,
                charge_point_id=item.charge_point_id,
                charge_point_code=item.charge_point_code,
                sessions_count=item.sessions_count,
                energy_kwh=kwh,
                energy_amount_vnd=item.energy_amount_vnd,
                idle_amount_vnd=item.idle_amount_vnd,
                total_invoice_vnd=item.total_invoice_vnd,
                debited_vnd=item.debited_vnd,
                awaiting_settlement_vnd=item.awaiting_settlement_vnd,
                unbilled_sessions=item.unbilled_sessions,
                unbilled_operating_kwh=unbilled_kwh,
            )
        )

    # Sort charge points by total_invoice_vnd desc, then charge_point_code
    cp_list.sort(
        key=lambda x: (x.total_invoice_vnd, x.energy_kwh),
        reverse=True,
    )

    summary = RevenueSummary(
        invoiced_sessions=total_invoiced_sessions,
        total_kwh=round(total_energy_wh / Decimal(1000), 4),
        energy_amount_vnd=total_energy_amount_vnd,
        idle_amount_vnd=total_idle_amount_vnd,
        total_invoice_vnd=total_invoice_vnd,
        debited_vnd=total_debited_vnd,
        awaiting_settlement_vnd=total_awaiting_settlement_vnd,
        unbilled_sessions=total_unbilled_sessions,
        unbilled_operating_kwh=round(total_unbilled_kwh, 4),
    )

    daily_timeline = [
        DailyRevenueItem(
            date=d.date,
            sessions_count=d.sessions_count,
            kwh=round(d.kwh, 4),
            invoice_vnd=d.invoice_vnd,
            debited_vnd=d.debited_vnd,
        )
        for d in sorted(daily_map.values(), key=lambda x: x.date)
    ]

    return start_dt, end_dt, cp_list, summary, daily_timeline


async def get_revenue_report(
    db: AsyncSession,
    query: RevenueReportQuery,
    owner_id: UUID | None = None,
) -> RevenueReportResponse:
    start_dt, end_dt, cp_list, summary, daily_timeline = await _compute_revenue_data(
        db, query, owner_id
    )

    total_items = len(cp_list)
    page_size = query.page_size
    total_pages = max(1, ceil(total_items / page_size))
    current_page = min(query.page, total_pages)
    offset = (current_page - 1) * page_size
    paginated_cps = cp_list[offset : offset + page_size]

    return RevenueReportResponse(
        from_date=start_dt,
        to_date=end_dt,
        timezone="Asia/Ho_Chi_Minh",
        summary=summary,
        charge_points=paginated_cps,
        daily_timeline=daily_timeline,
        pagination=PaginationMeta(
            page=current_page,
            page_size=page_size,
            total_items=total_items,
            total_pages=total_pages,
        ),
    )


async def export_revenue_report_csv(
    db: AsyncSession,
    query: RevenueReportQuery,
    owner_id: UUID | None = None,
) -> StreamingResponse:
    start_dt, end_dt, cp_list, _, _ = await _compute_revenue_data(db, query, owner_id)

    from_str = start_dt.isoformat()
    to_str = end_dt.isoformat()

    rows: list[list[Any]] = []
    for item in cp_list:
        rows.append(
            [
                from_str,
                to_str,
                "Asia/Ho_Chi_Minh",
                str(item.station_id),
                item.station_name,
                str(item.charge_point_id),
                item.charge_point_code,
                item.sessions_count,
                item.energy_kwh,
                item.energy_amount_vnd,
                item.idle_amount_vnd,
                item.total_invoice_vnd,
                item.debited_vnd,
            ]
        )

    filename = (
        f"revenue_report_{start_dt.strftime('%Y%m%d')}_{end_dt.strftime('%Y%m%d')}.csv"
    )
    return build_csv_streaming_response(filename, REVENUE_CSV_HEADERS, rows)
