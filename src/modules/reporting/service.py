from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from math import ceil
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import String, and_, case, cast, func, literal_column, select
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
from src.modules.reservations.models import Reservation
from src.modules.stations.models import ChargePoint, Station
from src.modules.wallet.models import Wallet, WalletLedger
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
    invoice_cohort_settled_vnd: int = 0
    awaiting_settlement_vnd: int = 0
    awaiting_settlement_sessions: int = 0
    legacy_exempt_sessions: int = 0
    legacy_exempt_vnd: int = 0
    free_sessions: int = 0
    reservation_fee_vnd: int = 0
    reservation_count: int = 0
    unbilled_sessions: int = 0
    unbilled_operating_kwh: Decimal = field(default_factory=lambda: Decimal(0))
    unbilled_missing_meter_sessions: int = 0


@dataclass
class _DailyAccumulator:
    date: str
    sessions_count: int = 0
    kwh: Decimal = field(default_factory=lambda: Decimal(0))
    invoice_vnd: int = 0
    debited_vnd: int = 0
    reservation_fee_vnd: int = 0


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
    "invoice_cohort_settled_vnd",
    "awaiting_settlement_vnd",
    "awaiting_settlement_sessions",
    "legacy_exempt_sessions",
    "legacy_exempt_vnd",
    "free_sessions",
    "reservation_fee_vnd",
    "reservation_count",
    "unbilled_sessions",
    "unbilled_operating_kwh",
    "unbilled_missing_meter_sessions",
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

    # 1. LATERAL correlated subquery aggregating InvoiceLine metrics per invoice using index (AC-6)
    line_lateral = (
        select(
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
        .where(InvoiceLine.invoice_id == Invoice.id)
        .correlate(Invoice)
        .subquery()
        .lateral("line_agg")
    )

    # 2. Invoiced sessions query within [start_dt, end_dt) with direct ledger lookup
    invoiced_query = (
        select(
            Invoice.id.label("invoice_id"),
            Invoice.session_id,
            Invoice.created_at.label("invoice_created_at"),
            Invoice.total_vnd.label("invoice_total_vnd"),
            ChargingSession.settlement_reason.label("settlement_reason"),
            Station.id.label("station_id"),
            Station.name.label("station_name"),
            ChargePoint.id.label("charge_point_id"),
            ChargePoint.code.label("charge_point_code"),
            func.coalesce(line_lateral.c.energy_wh, 0).label("energy_wh"),
            func.coalesce(line_lateral.c.energy_amount_vnd, 0).label(
                "energy_amount_vnd"
            ),
            func.coalesce(line_lateral.c.idle_amount_vnd, 0).label("idle_amount_vnd"),
            case(
                (
                    and_(
                        Wallet.id.is_not(None),
                        Wallet.driver_id == ChargingSession.driver_id,
                    ),
                    -WalletLedger.amount_vnd,
                ),
                else_=0,
            ).label("session_debited_vnd"),
        )
        .join(ChargingSession, ChargingSession.id == Invoice.session_id)
        .join(ChargePoint, ChargePoint.id == ChargingSession.charge_point_id)
        .join(Station, Station.id == ChargePoint.station_id)
        .outerjoin(line_lateral, literal_column("true"))
        .outerjoin(
            WalletLedger,
            and_(
                WalletLedger.entry_type == "charging_debit",
                WalletLedger.reference_type == "charging_session",
                WalletLedger.reference_id == cast(Invoice.session_id, String),
                WalletLedger.amount_vnd < 0,
            ),
        )
        .outerjoin(Wallet, Wallet.id == WalletLedger.wallet_id)
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

    # 3. Debits query within [start_dt, end_dt) filtered strictly by ledger.created_at (AC-3)
    debits_query = (
        select(
            WalletLedger.id.label("ledger_id"),
            (-WalletLedger.amount_vnd).label("debited_vnd"),
            WalletLedger.created_at.label("ledger_created_at"),
            Station.id.label("station_id"),
            Station.name.label("station_name"),
            ChargePoint.id.label("charge_point_id"),
            ChargePoint.code.label("charge_point_code"),
        )
        .join(Wallet, Wallet.id == WalletLedger.wallet_id)
        .join(
            ChargingSession,
            and_(
                WalletLedger.reference_type == "charging_session",
                WalletLedger.reference_id == cast(ChargingSession.id, String),
                Wallet.driver_id == ChargingSession.driver_id,
            ),
        )
        .join(ChargePoint, ChargePoint.id == ChargingSession.charge_point_id)
        .join(Station, Station.id == ChargePoint.station_id)
        .where(
            WalletLedger.created_at >= start_dt,
            WalletLedger.created_at < end_dt,
            WalletLedger.entry_type == "charging_debit",
            WalletLedger.amount_vnd < 0,
        )
    )

    if owner_id is not None:
        debits_query = debits_query.where(Station.owner_id == owner_id)
    if query.station_id is not None:
        debits_query = debits_query.where(Station.id == query.station_id)
    if query.charge_point_id is not None:
        debits_query = debits_query.where(ChargePoint.id == query.charge_point_id)

    debit_rows = (await db.execute(debits_query)).all()

    # 4. Reservation fee debits query within [start_dt, end_dt) (S-50 / AC-4)
    reservations_query = (
        select(
            WalletLedger.id.label("ledger_id"),
            (-WalletLedger.amount_vnd).label("reservation_fee_vnd"),
            WalletLedger.created_at.label("ledger_created_at"),
            Station.id.label("station_id"),
            Station.name.label("station_name"),
            ChargePoint.id.label("charge_point_id"),
            ChargePoint.code.label("charge_point_code"),
        )
        .join(Wallet, Wallet.id == WalletLedger.wallet_id)
        .join(
            Reservation,
            and_(
                WalletLedger.reference_type == "reservation",
                WalletLedger.reference_id == cast(Reservation.id, String),
                Wallet.driver_id == Reservation.driver_id,
            ),
        )
        .join(ChargePoint, ChargePoint.id == Reservation.charge_point_id)
        .join(Station, Station.id == Reservation.station_id)
        .where(
            WalletLedger.created_at >= start_dt,
            WalletLedger.created_at < end_dt,
            WalletLedger.entry_type == "reservation_fee",
            WalletLedger.amount_vnd < 0,
        )
    )

    if owner_id is not None:
        reservations_query = reservations_query.where(Station.owner_id == owner_id)
    if query.station_id is not None:
        reservations_query = reservations_query.where(Station.id == query.station_id)
    if query.charge_point_id is not None:
        reservations_query = reservations_query.where(
            ChargePoint.id == query.charge_point_id
        )

    reservation_rows = (await db.execute(reservations_query)).all()

    # 5. Unbilled operating sessions within [start_dt, end_dt) (AC-5)
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

    # 6. Accumulators and timeline initialization
    cp_map: dict[UUID, _CPAccumulator] = {}

    def _get_cp(s_id: UUID, s_name: str, cp_id: UUID, cp_code: str) -> _CPAccumulator:
        if cp_id not in cp_map:
            cp_map[cp_id] = _CPAccumulator(
                station_id=s_id,
                station_name=s_name,
                charge_point_id=cp_id,
                charge_point_code=cp_code,
            )
        return cp_map[cp_id]

    total_invoiced_sessions = 0
    total_energy_wh = Decimal(0)
    total_energy_amount_vnd = 0
    total_idle_amount_vnd = 0
    total_invoice_vnd = 0
    total_debited_vnd = 0
    total_invoice_cohort_settled_vnd = 0
    total_awaiting_settlement_vnd = 0
    total_awaiting_settlement_sessions = 0
    total_legacy_exempt_sessions = 0
    total_legacy_exempt_vnd = 0
    total_free_sessions = 0
    total_reservation_fee_vnd = 0
    total_reservation_count = 0

    # Daily timeline map (keyed by "YYYY-MM-DD")
    daily_map: dict[str, _DailyAccumulator] = {}
    curr_d = start_dt.date()
    end_d = end_dt.date()
    while curr_d < end_d:
        d_str = curr_d.isoformat()
        daily_map[d_str] = _DailyAccumulator(date=d_str)
        curr_d += timedelta(days=1)

    # Process invoiced sessions
    for row in invoiced_rows:
        inv_total = int(row.invoice_total_vnd)
        energy_wh = Decimal(str(row.energy_wh))
        energy_amt = int(row.energy_amount_vnd)
        idle_amt = int(row.idle_amount_vnd)
        cohort_debited = int(row.session_debited_vnd)
        settlement_reason = row.settlement_reason

        total_invoiced_sessions += 1
        total_energy_wh += energy_wh
        total_energy_amount_vnd += energy_amt
        total_idle_amount_vnd += idle_amt
        total_invoice_vnd += inv_total

        item = _get_cp(
            row.station_id,
            row.station_name,
            row.charge_point_id,
            row.charge_point_code,
        )
        item.sessions_count += 1
        item.energy_wh += energy_wh
        item.energy_amount_vnd += energy_amt
        item.idle_amount_vnd += idle_amt
        item.total_invoice_vnd += inv_total

        if settlement_reason == "legacy_exempt":
            total_legacy_exempt_sessions += 1
            total_legacy_exempt_vnd += inv_total
            item.legacy_exempt_sessions += 1
            item.legacy_exempt_vnd += inv_total
        elif settlement_reason == "zero_invoice" or inv_total == 0:
            total_free_sessions += 1
            item.free_sessions += 1
        else:
            total_invoice_cohort_settled_vnd += cohort_debited
            item.invoice_cohort_settled_vnd += cohort_debited
            unpaid = max(0, inv_total - cohort_debited)
            total_awaiting_settlement_vnd += unpaid
            item.awaiting_settlement_vnd += unpaid
            if unpaid > 0 or settlement_reason != "debited":
                total_awaiting_settlement_sessions += 1
                item.awaiting_settlement_sessions += 1

        # Timeline: invoices plotted on invoice creation date
        inv_created = row.invoice_created_at.astimezone(REPORT_TIMEZONE)
        d_str = inv_created.date().isoformat()
        if d_str in daily_map:
            d_entry = daily_map[d_str]
            d_entry.sessions_count += 1
            d_entry.kwh += energy_wh / Decimal(1000)
            d_entry.invoice_vnd += inv_total

    # Process debits occurred in period (AC-3: independent ledger period)
    for deb in debit_rows:
        deb_amt = int(deb.debited_vnd)
        total_debited_vnd += deb_amt

        item = _get_cp(
            deb.station_id,
            deb.station_name,
            deb.charge_point_id,
            deb.charge_point_code,
        )
        item.debited_vnd += deb_amt

        deb_created = deb.ledger_created_at.astimezone(REPORT_TIMEZONE)
        d_str = deb_created.date().isoformat()
        if d_str in daily_map:
            daily_map[d_str].debited_vnd += deb_amt

    # Process reservation fees occurred in period (AC-4: isolated from energy)
    for res in reservation_rows:
        res_amt = int(res.reservation_fee_vnd)
        total_reservation_fee_vnd += res_amt
        total_reservation_count += 1

        item = _get_cp(
            res.station_id,
            res.station_name,
            res.charge_point_id,
            res.charge_point_code,
        )
        item.reservation_fee_vnd += res_amt
        item.reservation_count += 1

        res_created = res.ledger_created_at.astimezone(REPORT_TIMEZONE)
        d_str = res_created.date().isoformat()
        if d_str in daily_map:
            daily_map[d_str].reservation_fee_vnd += res_amt

    # Process unbilled sessions (AC-5: distinguish missing meter vs 0 kWh)
    total_unbilled_sessions = len(unbilled_rows)
    total_unbilled_missing_meter_sessions = 0
    total_unbilled_kwh = Decimal(0)
    for ub in unbilled_rows:
        item = _get_cp(
            ub.station_id,
            ub.station_name,
            ub.charge_point_id,
            ub.charge_point_code,
        )
        item.unbilled_sessions += 1

        if ub.energy_kwh is None:
            total_unbilled_missing_meter_sessions += 1
            item.unbilled_missing_meter_sessions += 1
        else:
            ub_kwh = Decimal(str(ub.energy_kwh))
            total_unbilled_kwh += ub_kwh
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
                invoice_cohort_settled_vnd=item.invoice_cohort_settled_vnd,
                awaiting_settlement_vnd=item.awaiting_settlement_vnd,
                awaiting_settlement_sessions=item.awaiting_settlement_sessions,
                legacy_exempt_sessions=item.legacy_exempt_sessions,
                legacy_exempt_vnd=item.legacy_exempt_vnd,
                free_sessions=item.free_sessions,
                reservation_fee_vnd=item.reservation_fee_vnd,
                reservation_count=item.reservation_count,
                unbilled_sessions=item.unbilled_sessions,
                unbilled_operating_kwh=unbilled_kwh,
                unbilled_missing_meter_sessions=item.unbilled_missing_meter_sessions,
            )
        )

    # Sort charge points by total_invoice_vnd desc, then debited_vnd desc, then energy_kwh desc
    cp_list.sort(
        key=lambda x: (x.total_invoice_vnd, x.debited_vnd, x.energy_kwh),
        reverse=True,
    )

    summary = RevenueSummary(
        invoiced_sessions=total_invoiced_sessions,
        total_kwh=round(total_energy_wh / Decimal(1000), 4),
        energy_amount_vnd=total_energy_amount_vnd,
        idle_amount_vnd=total_idle_amount_vnd,
        total_invoice_vnd=total_invoice_vnd,
        debited_vnd=total_debited_vnd,
        invoice_cohort_settled_vnd=total_invoice_cohort_settled_vnd,
        awaiting_settlement_vnd=total_awaiting_settlement_vnd,
        awaiting_settlement_sessions=total_awaiting_settlement_sessions,
        legacy_exempt_sessions=total_legacy_exempt_sessions,
        legacy_exempt_vnd=total_legacy_exempt_vnd,
        free_sessions=total_free_sessions,
        reservation_fee_vnd=total_reservation_fee_vnd,
        reservation_count=total_reservation_count,
        unbilled_sessions=total_unbilled_sessions,
        unbilled_operating_kwh=round(total_unbilled_kwh, 4),
        unbilled_missing_meter_sessions=total_unbilled_missing_meter_sessions,
    )

    daily_timeline = [
        DailyRevenueItem(
            date=d.date,
            sessions_count=d.sessions_count,
            kwh=round(d.kwh, 4),
            invoice_vnd=d.invoice_vnd,
            debited_vnd=d.debited_vnd,
            reservation_fee_vnd=d.reservation_fee_vnd,
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
                item.invoice_cohort_settled_vnd,
                item.awaiting_settlement_vnd,
                item.awaiting_settlement_sessions,
                item.legacy_exempt_sessions,
                item.legacy_exempt_vnd,
                item.free_sessions,
                item.reservation_fee_vnd,
                item.reservation_count,
                item.unbilled_sessions,
                item.unbilled_operating_kwh,
                item.unbilled_missing_meter_sessions,
            ]
        )

    filename = (
        f"revenue_report_{start_dt.strftime('%Y%m%d')}_{end_dt.strftime('%Y%m%d')}.csv"
    )
    return build_csv_streaming_response(filename, REVENUE_CSV_HEADERS, rows)
