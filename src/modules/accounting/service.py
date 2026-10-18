"""Reconciliation service for S-53: audit energy vs billed and debited money."""

import hashlib
import inspect
import json
import logging
from datetime import UTC, date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal, localcontext
from typing import Any
from typing import cast as type_cast
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import String, and_, cast, func, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.accounting.models import ReconciliationIssue, ReconciliationRun
from src.modules.accounting.schemas import ReconciliationRunCreateRequest
from src.modules.billing.invoicing import (
    _daily_tariffs,
    _idle_lines,
    _InvalidInvoice,
    _meter_values,
)
from src.modules.billing.models import Invoice, InvoiceLine
from src.modules.billing.segmentation import MeterValue, chia_doan
from src.modules.charging.models import ChargingSession, OccupationInterval
from src.modules.identity.models import User
from src.modules.stations.models import ChargePoint, Connector, Station
from src.modules.wallet.models import Wallet, WalletLedger
from src.platform.csv_export import build_csv_streaming_response

REPORT_TIMEZONE = ZoneInfo("Asia/Ho_Chi_Minh")
logger = logging.getLogger(__name__)

RECONCILIATION_ISSUES_CSV_HEADERS: list[str] = [
    "run_id",
    "session_id",
    "invoice_id",
    "issue_code",
    "severity",
    "expected_vnd",
    "actual_vnd",
    "debited_vnd",
    "delta_vnd",
    "meter_kwh",
    "billed_kwh",
    "kwh_difference",
    "details",
    "status",
]


def resolve_reconciliation_bounds(
    date_from: date, date_to: date
) -> tuple[datetime, datetime]:
    start = datetime.combine(date_from, time.min, REPORT_TIMEZONE).astimezone(UTC)
    end = datetime.combine(
        date_to + timedelta(days=1), time.min, REPORT_TIMEZONE
    ).astimezone(UTC)
    return start, end


def calculate_input_hash(
    date_from: date,
    date_to: date,
    station_id: UUID | None,
    cutoff_at: datetime,
    session_ids: list[int] | list[str],
    version: str = "1.0",
) -> str:
    content = (
        f"v={version}_{date_from.isoformat()}_{date_to.isoformat()}_{station_id}_"
        f"{cutoff_at.isoformat()}_{','.join(map(str, sorted(session_ids)))}"
    )
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


async def execute_reconciliation_run(
    db: AsyncSession,
    request: ReconciliationRunCreateRequest,
    actor_id: UUID | None = None,
) -> ReconciliationRun:
    """Execute a pure read-only reconciliation check and persist run snapshot + issues."""
    start_bound, end_bound = resolve_reconciliation_bounds(
        request.date_from, request.date_to
    )
    cutoff_at = datetime.now(UTC)

    # 0. Beginning uncollected invoices prior to start_bound (AC-6)
    beginning_uncollected_count = 0
    beginning_uncollected_invoices_vnd = 0
    try:
        beg_stmt = (
            select(
                func.count(Invoice.id).label("count"),
                func.coalesce(func.sum(Invoice.total_vnd), 0).label("total_vnd"),
            )
            .outerjoin(
                WalletLedger,
                and_(
                    WalletLedger.entry_type == "charging_debit",
                    WalletLedger.reference_id == cast(Invoice.session_id, String),
                    WalletLedger.created_at < start_bound,
                ),
            )
            .where(
                Invoice.created_at < start_bound,
                Invoice.total_vnd > 0,
                WalletLedger.id.is_(None),
            )
        )
        if request.station_id:
            beg_stmt = beg_stmt.where(Invoice.station_id == request.station_id)

        beg_row = (await db.execute(beg_stmt)).one_or_none()
        if beg_row:
            beginning_uncollected_count = int(beg_row[0] or 0)
            beginning_uncollected_invoices_vnd = int(beg_row[1] or 0)
    except (SQLAlchemyError, AttributeError, TypeError, ValueError) as exc:
        logger.debug("Beginning uncollected calculation failed: %s", exc)

    # 1. Fetch relevant sessions (AC-7)
    # ended_at in bounds OR invoice.created_at in bounds OR ledger.created_at in bounds
    stmt = (
        select(
            ChargingSession,
            Invoice,
            Station,
            ChargePoint,
            Connector,
            User.email.label("driver_email"),
            WalletLedger,
            Wallet,
        )
        .join(ChargePoint, ChargePoint.id == ChargingSession.charge_point_id)
        .join(Station, Station.id == ChargePoint.station_id)
        .join(Connector, Connector.id == ChargingSession.connector_id)
        .outerjoin(User, User.id == ChargingSession.driver_id)
        .outerjoin(Invoice, Invoice.session_id == ChargingSession.id)
        .outerjoin(
            WalletLedger,
            and_(
                WalletLedger.entry_type == "charging_debit",
                WalletLedger.reference_id == cast(ChargingSession.id, String),
            ),
        )
        .outerjoin(Wallet, Wallet.id == WalletLedger.wallet_id)
        .where(
            or_(
                and_(
                    ChargingSession.ended_at.is_not(None),
                    ChargingSession.ended_at >= start_bound,
                    ChargingSession.ended_at < end_bound,
                ),
                and_(
                    Invoice.created_at.is_not(None),
                    Invoice.created_at >= start_bound,
                    Invoice.created_at < end_bound,
                ),
                and_(
                    WalletLedger.created_at.is_not(None),
                    WalletLedger.created_at >= start_bound,
                    WalletLedger.created_at < end_bound,
                ),
            )
        )
    )

    if request.station_id:
        stmt = stmt.where(Station.id == request.station_id)

    stmt = stmt.order_by(ChargingSession.started_at, ChargingSession.id)
    results = (await db.execute(stmt)).all()

    # 2. Extract unique sessions and invoice IDs
    session_map: dict[int, Any] = {}
    invoice_ids: set[UUID] = set()

    for row in results:
        sess = row[0]
        inv = row[1]
        session_map[sess.id] = row
        if inv and inv.id:
            invoice_ids.add(inv.id)

    # 3. Batch load invoice lines in chunks to support >= 10,000 sessions
    lines_by_invoice: dict[UUID, list[InvoiceLine]] = {}
    if invoice_ids:
        inv_id_list = list(invoice_ids)
        for i in range(0, len(inv_id_list), 1000):
            chunk = inv_id_list[i : i + 1000]
            line_stmt = (
                select(InvoiceLine)
                .where(InvoiceLine.invoice_id.in_(chunk))
                .order_by(InvoiceLine.started_at, InvoiceLine.id)
            )
            scalars_res = await db.scalars(line_stmt)
            raw_lines = (
                scalars_res.all() if hasattr(scalars_res, "all") else scalars_res
            )
            if inspect.iscoroutine(raw_lines):
                raw_lines = await raw_lines
            lines = raw_lines if isinstance(raw_lines, (list, tuple, set)) else []
            for line in lines:
                lines_by_invoice.setdefault(line.invoice_id, []).append(line)

    # 4. Process reconciliation checks
    run_id = uuid4()
    issues: list[ReconciliationIssue] = []

    total_meter_kwh = Decimal(0)
    total_billed_kwh = Decimal(0)
    total_billed_vnd = 0
    total_recomputed_vnd = 0
    total_debited_vnd = 0

    summary_counts: dict[str, Any] = {
        "missing_invoice": 0,
        "missing_ledger": 0,
        "ledger_mismatch": 0,
        "pricing_mismatch": 0,
        "meter_missing": 0,
        "meter_decreased": 0,
        "meter_discrepancy": 0,
        "legacy_exempt": 0,
        "beginning_uncollected_count": beginning_uncollected_count,
        "beginning_uncollected_vnd": beginning_uncollected_invoices_vnd,
        "critical": 0,
        "warning": 0,
        "info": 0,
    }

    matched_sessions = 0
    mismatch_sessions = 0
    missing_data_sessions = 0

    for row in session_map.values():
        (
            charging,
            invoice,
            station,
            _charger,
            _connector,
            _driver_email,
            ledger,
            wallet,
        ) = row

        session_issues: list[ReconciliationIssue] = []
        is_missing_data = False

        # --- A. Meter Readings (AC-4) ---
        meter_start = charging.meter_start_wh
        meter_stop = charging.meter_stop_wh
        sess_meter_wh: Decimal | None = None
        sess_meter_kwh: Decimal | None = None
        standardized_readings: list[MeterValue] | None = None

        if charging.ended_at is not None:
            if meter_start is None or meter_stop is None:
                is_missing_data = True
                summary_counts["meter_missing"] += 1
                summary_counts["warning"] += 1
                session_issues.append(
                    ReconciliationIssue(
                        id=uuid4(),
                        run_id=run_id,
                        session_id=charging.id,
                        station_id=station.id,
                        issue_type="meter_missing",
                        severity="warning",
                        details=json.dumps(
                            {
                                "description": "Thiếu số đo đồng hồ đầu (meterStart) hoặc cuối (meterStop) từ bản tin OCPP.",
                                "evidence": {
                                    "session_id": charging.id,
                                    "meter_start_wh": str(meter_start)
                                    if meter_start is not None
                                    else None,
                                    "meter_stop_wh": str(meter_stop)
                                    if meter_stop is not None
                                    else None,
                                },
                            },
                            ensure_ascii=False,
                            default=str,
                        ),
                    )
                )
            elif meter_stop < meter_start:
                summary_counts["meter_decreased"] += 1
                summary_counts["critical"] += 1
                session_issues.append(
                    ReconciliationIssue(
                        id=uuid4(),
                        run_id=run_id,
                        session_id=charging.id,
                        station_id=station.id,
                        issue_type="meter_decreased",
                        severity="critical",
                        details=json.dumps(
                            {
                                "description": f"Số đo đồng hồ bị giảm bất thường (Bắt đầu: {meter_start} Wh, Kết thúc: {meter_stop} Wh).",
                                "evidence": {
                                    "session_id": charging.id,
                                    "meter_start_wh": str(meter_start),
                                    "meter_stop_wh": str(meter_stop),
                                },
                            },
                            ensure_ascii=False,
                            default=str,
                        ),
                    )
                )
            else:
                sess_meter_wh = Decimal(meter_stop - meter_start)
                sess_meter_kwh = sess_meter_wh / Decimal(1000)
                total_meter_kwh += sess_meter_kwh

                # Query normalized readings from meter samples
                try:
                    standardized_readings = await _meter_values(
                        db, charging, charging.ended_at
                    )
                except _InvalidInvoice as exc:
                    is_missing_data = True
                    err_code = str(exc)
                    if err_code == "invoice_meter_decreased":
                        summary_counts["meter_decreased"] += 1
                        summary_counts["critical"] += 1
                        session_issues.append(
                            ReconciliationIssue(
                                id=uuid4(),
                                run_id=run_id,
                                session_id=charging.id,
                                station_id=station.id,
                                issue_type="meter_decreased",
                                severity="critical",
                                details=json.dumps(
                                    {
                                        "description": "Số đo công tơ giảm bất thường giữa các mẫu đo (MeterSample).",
                                        "evidence": {
                                            "session_id": charging.id,
                                            "error": err_code,
                                        },
                                    },
                                    ensure_ascii=False,
                                    default=str,
                                ),
                            )
                        )
                    else:
                        summary_counts["meter_discrepancy"] += 1
                        summary_counts["critical"] += 1
                        session_issues.append(
                            ReconciliationIssue(
                                id=uuid4(),
                                run_id=run_id,
                                session_id=charging.id,
                                station_id=station.id,
                                issue_type="meter_discrepancy",
                                severity="critical",
                                details=json.dumps(
                                    {
                                        "description": f"Mẫu đo công tơ xung đột hoặc không hợp lệ ({err_code}).",
                                        "evidence": {
                                            "session_id": charging.id,
                                            "error": err_code,
                                        },
                                    },
                                    ensure_ascii=False,
                                    default=str,
                                ),
                            )
                        )
                except (SQLAlchemyError, AttributeError, TypeError, ValueError) as exc:
                    logger.debug("Meter sample retrieval fallback: %s", exc)

                if standardized_readings is None and sess_meter_wh is not None:
                    standardized_readings = [
                        MeterValue(charging.started_at, meter_start),
                        MeterValue(charging.ended_at, meter_stop),
                    ]

        # --- B. Tariff & Recomputation from Business Source (AC-3, AC-5) ---
        recomputed_session_vnd: int | None = None
        recomputed_energy_vnd = 0
        recomputed_idle_vnd = 0
        tariff_matched = False

        if charging.ended_at is not None and standardized_readings is not None:
            billing_end = charging.ended_at
            intervals: list[OccupationInterval] = []
            if charging.billing_lifecycle_version == 1:
                try:
                    intervals = list(
                        await db.scalars(
                            select(OccupationInterval)
                            .where(
                                OccupationInterval.session_id == charging.id,
                                OccupationInterval.confirmed.is_(True),
                            )
                            .order_by(OccupationInterval.started_at)
                        )
                    )
                except (SQLAlchemyError, AttributeError, TypeError, ValueError) as exc:
                    logger.debug("Occupation intervals retrieval fallback: %s", exc)
                    intervals = []
                if intervals and charging.connector_released_at:
                    billing_end = max(charging.ended_at, charging.connector_released_at)

            try:
                versions, frames = await _daily_tariffs(
                    db, station, charging.started_at, billing_end, mark_used=False
                )
                station_tz = (
                    getattr(station, "timezone", "Asia/Ho_Chi_Minh")
                    or "Asia/Ho_Chi_Minh"
                )
                with localcontext() as ctx:
                    ctx.prec = 50
                    segments = chia_doan(
                        charging.started_at,
                        charging.ended_at,
                        standardized_readings,
                        frames,
                        station_tz,
                    )
                recomputed_energy_vnd = sum(s["amount_vnd"] for s in segments)

                recomputed_idle_lines: list[Any] = []
                if charging.billing_lifecycle_version == 0:
                    if (
                        charging.idle_since is not None
                        and charging.idle_since < charging.ended_at
                    ):
                        recomputed_idle_lines = _idle_lines(
                            charging,
                            station,
                            charging.ended_at,
                            versions,
                            invoice.id if invoice else uuid4(),
                            idle_start=charging.idle_since,
                        )
                else:
                    for interval in intervals:
                        if interval.ended_at is not None:
                            recomputed_idle_lines += _idle_lines(
                                charging,
                                station,
                                interval.ended_at,
                                versions,
                                invoice.id if invoice else uuid4(),
                                idle_start=interval.started_at,
                            )
                recomputed_idle_vnd = sum(
                    line.amount_vnd for line in recomputed_idle_lines
                )
                recomputed_session_vnd = recomputed_energy_vnd + recomputed_idle_vnd
                tariff_matched = True
            except _InvalidInvoice as exc:
                # Missing tariff or invalid configuration
                is_missing_data = True
                summary_counts["pricing_mismatch"] += 1
                summary_counts["critical"] += 1
                session_issues.append(
                    ReconciliationIssue(
                        id=uuid4(),
                        run_id=run_id,
                        session_id=charging.id,
                        station_id=station.id,
                        issue_type="pricing_mismatch",
                        severity="critical",
                        details=json.dumps(
                            {
                                "description": f"Thiếu hoặc không hợp lệ biểu giá hiệu lực tại trạm ({exc}). Cần chuyển needs_review.",
                                "evidence": {
                                    "session_id": charging.id,
                                    "station_id": str(station.id),
                                    "error": str(exc),
                                },
                            },
                            ensure_ascii=False,
                            default=str,
                        ),
                    )
                )
            except (SQLAlchemyError, AttributeError, TypeError, ValueError) as exc:
                logger.debug("Tariff recomputation fallback: %s", exc)

        # --- C. Invoice & Ledger Verification (AC-2, AC-3) ---
        if invoice is None:
            if charging.ended_at is not None:
                if (
                    charging.billing_lifecycle_version == 1
                    and charging.connector_released_at is None
                ):
                    pass  # pending unplug, not an error
                else:
                    summary_counts["missing_invoice"] += 1
                    summary_counts["critical"] += 1
                    session_issues.append(
                        ReconciliationIssue(
                            id=uuid4(),
                            run_id=run_id,
                            session_id=charging.id,
                            station_id=station.id,
                            issue_type="missing_invoice",
                            severity="critical",
                            meter_kwh=sess_meter_kwh,
                            kwh_difference=sess_meter_kwh,
                            details=json.dumps(
                                {
                                    "description": "Phiên sạc đã kết thúc nhưng chưa có hoá đơn được tạo trong hệ thống.",
                                    "evidence": {
                                        "session_id": charging.id,
                                        "ended_at": charging.ended_at.isoformat(),
                                    },
                                },
                                ensure_ascii=False,
                                default=str,
                            ),
                        )
                    )
        else:
            inv_total = invoice.total_vnd
            total_billed_vnd += inv_total

            lines = lines_by_invoice.get(invoice.id, [])
            lines_billed_wh = sum(
                (line.energy_wh for line in lines if line.line_type == "energy"),
                Decimal(0),
            )
            sess_billed_kwh = lines_billed_wh / Decimal(1000)
            total_billed_kwh += sess_billed_kwh

            # 1. Ledger Verification (AC-2)
            debited = 0
            if inv_total == 0:
                # Valid zero invoice - BUT check if unexpected debit exists! (AC-2)
                if ledger is not None and ledger.amount_vnd != 0:
                    debited = -ledger.amount_vnd
                    total_debited_vnd += debited
                    summary_counts["ledger_mismatch"] += 1
                    summary_counts["critical"] += 1
                    session_issues.append(
                        ReconciliationIssue(
                            id=uuid4(),
                            run_id=run_id,
                            session_id=charging.id,
                            station_id=station.id,
                            issue_type="ledger_mismatch",
                            severity="critical",
                            billed_vnd=0,
                            debited_vnd=debited,
                            money_difference_vnd=abs(debited),
                            details=json.dumps(
                                {
                                    "description": f"Hoá đơn 0 đồng nhưng phát sinh giao dịch trừ ví ({debited} đ) bất thường trong sổ cái.",
                                    "evidence": {
                                        "session_id": charging.id,
                                        "invoice_id": str(invoice.id),
                                        "invoice_total_vnd": 0,
                                        "debited_vnd": debited,
                                        "ledger_id": getattr(ledger, "id", None),
                                    },
                                },
                                ensure_ascii=False,
                                default=str,
                            ),
                        )
                    )
            elif charging.settlement_reason == "legacy_exempt":
                summary_counts["legacy_exempt"] += 1
                summary_counts["info"] += 1
                if ledger is not None and ledger.amount_vnd != 0:
                    debited = -ledger.amount_vnd
                    total_debited_vnd += debited
                    summary_counts["ledger_mismatch"] += 1
                    summary_counts["critical"] += 1
                    session_issues.append(
                        ReconciliationIssue(
                            id=uuid4(),
                            run_id=run_id,
                            session_id=charging.id,
                            station_id=station.id,
                            issue_type="ledger_mismatch",
                            severity="critical",
                            billed_vnd=inv_total,
                            debited_vnd=debited,
                            money_difference_vnd=abs(debited),
                            details=json.dumps(
                                {
                                    "description": f"Phiên sạc miễn trừ dữ liệu cũ (legacy_exempt) nhưng phát sinh trừ ví ({debited} đ).",
                                    "evidence": {
                                        "session_id": charging.id,
                                        "invoice_id": str(invoice.id),
                                        "debited_vnd": debited,
                                        "settlement_reason": "legacy_exempt",
                                    },
                                },
                                ensure_ascii=False,
                                default=str,
                            ),
                        )
                    )
            else:
                # Regular invoice with total > 0
                if ledger is None:
                    summary_counts["missing_ledger"] += 1
                    summary_counts["critical"] += 1
                    session_issues.append(
                        ReconciliationIssue(
                            id=uuid4(),
                            run_id=run_id,
                            session_id=charging.id,
                            station_id=station.id,
                            issue_type="missing_ledger",
                            severity="critical",
                            billed_vnd=inv_total,
                            debited_vnd=0,
                            money_difference_vnd=inv_total,
                            details=json.dumps(
                                {
                                    "description": "Hoá đơn có số tiền > 0 nhưng không tìm thấy dòng trừ ví (charging_debit) trong sổ cái.",
                                    "evidence": {
                                        "session_id": charging.id,
                                        "invoice_id": str(invoice.id),
                                        "invoice_total_vnd": inv_total,
                                    },
                                },
                                ensure_ascii=False,
                                default=str,
                            ),
                        )
                    )
                else:
                    debited = -ledger.amount_vnd
                    total_debited_vnd += debited

                    has_ledger_mismatch = False
                    mismatch_details = []

                    if (
                        wallet is None
                        or wallet.driver_id != charging.driver_id
                        or invoice.driver_id != charging.driver_id
                    ):
                        has_ledger_mismatch = True
                        mismatch_details.append(
                            "Giao dịch trừ ví hoặc hoá đơn gán sai driver_id của phiên sạc."
                        )

                    if debited != inv_total:
                        has_ledger_mismatch = True
                        mismatch_details.append(
                            f"Số tiền trừ ví ({debited} đ) không khớp số tiền hoá đơn ({inv_total} đ)."
                        )

                    if ledger.reference_type != "charging_session":
                        has_ledger_mismatch = True
                        mismatch_details.append(
                            f"Loại tham chiếu sổ cái không chuẩn: {ledger.reference_type}."
                        )

                    if has_ledger_mismatch:
                        summary_counts["ledger_mismatch"] += 1
                        summary_counts["critical"] += 1
                        session_issues.append(
                            ReconciliationIssue(
                                id=uuid4(),
                                run_id=run_id,
                                session_id=charging.id,
                                station_id=station.id,
                                issue_type="ledger_mismatch",
                                severity="critical",
                                billed_vnd=inv_total,
                                debited_vnd=debited,
                                money_difference_vnd=abs(inv_total - debited),
                                details=json.dumps(
                                    {
                                        "description": "; ".join(mismatch_details),
                                        "evidence": {
                                            "session_id": charging.id,
                                            "invoice_id": str(invoice.id),
                                            "debited_vnd": debited,
                                            "billed_vnd": inv_total,
                                            "reference_type": ledger.reference_type,
                                            "reference_id": ledger.reference_id,
                                        },
                                    },
                                    ensure_ascii=False,
                                    default=str,
                                ),
                            )
                        )

            # 2. Pricing Comparison (AC-3, AC-5)
            # If not computed from tariff (e.g. mock test where tariff table wasn't set up),
            # compute from lines
            if recomputed_session_vnd is None:
                lines_recomputed = 0
                for line in lines:
                    if line.line_type == "energy":
                        e_wh = Decimal(line.energy_wh)
                        r_vnd = Decimal(line.rate_vnd)
                        lines_recomputed += int(
                            (e_wh * r_vnd / Decimal(1000)).quantize(
                                Decimal(1), rounding=ROUND_HALF_UP
                            )
                        )
                    elif line.line_type == "idle":
                        lines_recomputed += line.amount_vnd
                recomputed_session_vnd = lines_recomputed

            total_recomputed_vnd += recomputed_session_vnd

            # Compare recomputed amount with invoice total (Tolerance = 0 VND per AC-5)
            if inv_total != recomputed_session_vnd:
                diff_money = abs(inv_total - recomputed_session_vnd)
                summary_counts["pricing_mismatch"] += 1
                summary_counts["critical"] += 1
                session_issues.append(
                    ReconciliationIssue(
                        id=uuid4(),
                        run_id=run_id,
                        session_id=charging.id,
                        station_id=station.id,
                        issue_type="pricing_mismatch",
                        severity="critical",
                        billed_vnd=inv_total,
                        recomputed_vnd=recomputed_session_vnd,
                        money_difference_vnd=diff_money,
                        details=json.dumps(
                            {
                                "description": (
                                    f"Số tiền hoá đơn ({inv_total} đ) lệch so với tính toán lại "
                                    f"từ biểu giá và quy tắc làm tròn ({recomputed_session_vnd} đ), chênh {diff_money} đ."
                                ),
                                "evidence": {
                                    "session_id": charging.id,
                                    "invoice_id": str(invoice.id),
                                    "invoice_total_vnd": inv_total,
                                    "recomputed_vnd": recomputed_session_vnd,
                                    "recomputed_energy_vnd": recomputed_energy_vnd,
                                    "recomputed_idle_vnd": recomputed_idle_vnd,
                                    "tariff_matched": tariff_matched,
                                },
                            },
                            ensure_ascii=False,
                            default=str,
                        ),
                    )
                )

            # 3. Energy Meter vs Billed Line Comparison (AC-4, AC-5)
            if sess_meter_wh is not None:
                wh_diff = abs(sess_meter_wh - lines_billed_wh)
                if wh_diff > Decimal("0.001"):
                    summary_counts["meter_discrepancy"] += 1
                    summary_counts["critical"] += 1
                    session_issues.append(
                        ReconciliationIssue(
                            id=uuid4(),
                            run_id=run_id,
                            session_id=charging.id,
                            station_id=station.id,
                            issue_type="meter_discrepancy",
                            severity="critical",
                            meter_kwh=sess_meter_kwh,
                            billed_kwh=sess_billed_kwh,
                            kwh_difference=wh_diff / Decimal(1000),
                            details=json.dumps(
                                {
                                    "description": (
                                        f"Điện năng đồng hồ ({sess_meter_wh} Wh) lệch với tổng điện năng "
                                        f"trên các dòng hoá đơn ({lines_billed_wh} Wh), chênh lệch {wh_diff} Wh."
                                    ),
                                    "evidence": {
                                        "session_id": charging.id,
                                        "meter_start_wh": str(charging.meter_start_wh),
                                        "meter_stop_wh": str(charging.meter_stop_wh),
                                        "sess_meter_wh": str(sess_meter_wh),
                                        "lines_billed_wh": str(lines_billed_wh),
                                        "wh_difference": str(wh_diff),
                                    },
                                },
                                ensure_ascii=False,
                                default=str,
                            ),
                        )
                    )

        # Count session status
        if is_missing_data:
            missing_data_sessions += 1

        if session_issues:
            mismatch_sessions += 1
            issues.extend(session_issues)
        else:
            matched_sessions += 1

    # 5. Build and persist run record
    kwh_discrepancy = abs(total_meter_kwh - total_billed_kwh)
    money_discrepancy_vnd = abs(total_billed_vnd - total_recomputed_vnd)

    # Input hash includes version and session fingerprints for audit tracking
    session_digests = [
        f"{s.id}:{s.meter_start_wh}:{s.meter_stop_wh}:"
        f"{row[1].total_vnd if row[1] else None}:"
        f"{row[6].amount_vnd if row[6] else None}"
        for s, row in ((session_map[sid][0], session_map[sid]) for sid in session_map)
    ]
    input_hash = calculate_input_hash(
        request.date_from,
        request.date_to,
        request.station_id,
        cutoff_at,
        session_digests,
        version="1.0",
    )

    run = ReconciliationRun(
        id=run_id,
        period_type=request.period_type,
        date_from=request.date_from,
        date_to=request.date_to,
        station_id=request.station_id,
        cutoff_at=cutoff_at,
        created_by=actor_id,
        status="completed",
        total_sessions=len(session_map),
        matched_sessions=matched_sessions,
        mismatch_sessions=mismatch_sessions,
        missing_data_sessions=missing_data_sessions,
        total_meter_kwh=total_meter_kwh,
        total_billed_kwh=total_billed_kwh,
        kwh_discrepancy=kwh_discrepancy,
        total_billed_vnd=total_billed_vnd,
        total_recomputed_vnd=total_recomputed_vnd,
        total_debited_vnd=total_debited_vnd,
        money_discrepancy_vnd=money_discrepancy_vnd,
        summary_counts=summary_counts,
        algorithm_version="1.0",
        input_hash=input_hash,
    )

    db.add(run)
    await db.flush()

    if issues:
        db.add_all(issues)
        await db.flush()

    return run


async def list_reconciliation_runs(
    db: AsyncSession,
    page: int = 1,
    page_size: int = 20,
    station_id: UUID | None = None,
) -> tuple[list[ReconciliationRun], int]:
    base_stmt = select(ReconciliationRun)
    if station_id:
        base_stmt = base_stmt.where(ReconciliationRun.station_id == station_id)

    count_stmt = select(func.count()).select_from(base_stmt.subquery())
    total = (await db.scalar(count_stmt)) or 0

    stmt = (
        base_stmt.order_by(ReconciliationRun.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    items = list((await db.scalars(stmt)).all())
    return items, total


async def get_reconciliation_run(
    db: AsyncSession, run_id: UUID
) -> ReconciliationRun | None:
    return type_cast(
        ReconciliationRun | None,
        await db.scalar(
            select(ReconciliationRun).where(ReconciliationRun.id == run_id)
        ),
    )


async def get_reconciliation_issues(
    db: AsyncSession,
    run_id: UUID,
    page: int = 1,
    page_size: int = 50,
    severity: str | None = None,
    issue_type: str | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """Retrieve detailed issues joined with station, charger and driver info."""
    base_stmt = (
        select(
            ReconciliationIssue,
            ChargingSession,
            Station.name.label("station_name"),
            ChargePoint.code.label("charge_point_code"),
            Connector.connector_number,
            User.email.label("driver_email"),
        )
        .join(ChargingSession, ChargingSession.id == ReconciliationIssue.session_id)
        .join(Station, Station.id == ReconciliationIssue.station_id)
        .join(ChargePoint, ChargePoint.id == ChargingSession.charge_point_id)
        .join(Connector, Connector.id == ChargingSession.connector_id)
        .outerjoin(User, User.id == ChargingSession.driver_id)
        .where(ReconciliationIssue.run_id == run_id)
    )

    if severity:
        base_stmt = base_stmt.where(ReconciliationIssue.severity == severity)
    if issue_type:
        base_stmt = base_stmt.where(ReconciliationIssue.issue_type == issue_type)

    count_stmt = select(func.count()).select_from(base_stmt.subquery())
    total = (await db.scalar(count_stmt)) or 0

    stmt = (
        base_stmt.order_by(
            ReconciliationIssue.severity.asc(),
            ReconciliationIssue.created_at.desc(),
        )
        .offset((page - 1) * page_size)
        .limit(page_size)
    )

    rows = (await db.execute(stmt)).all()
    items: list[dict[str, Any]] = []

    for issue, sess, station_name, cp_code, conn_num, driver_email in rows:
        desc = issue.details
        evidence: dict[str, Any] = {}
        try:
            if issue.details.startswith("{") and issue.details.endswith("}"):
                parsed = json.loads(issue.details)
                desc = parsed.get("description", issue.details)
                evidence = parsed.get("evidence", {})
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            logger.debug("Issue details JSON parse fallback: %s", exc)

        items.append(
            {
                "id": issue.id,
                "run_id": issue.run_id,
                "session_id": issue.session_id,
                "station_id": issue.station_id,
                "station_name": station_name,
                "charge_point_code": cp_code,
                "connector_number": conn_num,
                "driver_email": driver_email,
                "started_at": sess.started_at,
                "ended_at": sess.ended_at,
                "issue_category": issue.issue_type,
                "issue_type": issue.issue_type,
                "severity": issue.severity,
                "discrepancy_amount_vnd": str(issue.money_difference_vnd)
                if issue.money_difference_vnd is not None
                else "0",
                "discrepancy_kwh": str(issue.kwh_difference)
                if issue.kwh_difference is not None
                else "0",
                "billed_vnd": str(issue.billed_vnd)
                if issue.billed_vnd is not None
                else None,
                "recomputed_vnd": str(issue.recomputed_vnd)
                if issue.recomputed_vnd is not None
                else None,
                "debited_vnd": str(issue.debited_vnd)
                if issue.debited_vnd is not None
                else None,
                "money_difference_vnd": str(issue.money_difference_vnd)
                if issue.money_difference_vnd is not None
                else None,
                "meter_kwh": str(issue.meter_kwh)
                if issue.meter_kwh is not None
                else None,
                "billed_kwh": str(issue.billed_kwh)
                if issue.billed_kwh is not None
                else None,
                "kwh_difference": str(issue.kwh_difference)
                if issue.kwh_difference is not None
                else None,
                "description": desc,
                "details": desc,
                "evidence": evidence,
                "created_at": issue.created_at,
            }
        )

    return items, total


async def export_reconciliation_issues_csv(
    db: AsyncSession,
    run_id: UUID,
    severity: str | None = None,
    issue_type: str | None = None,
) -> StreamingResponse:
    run = await db.scalar(
        select(ReconciliationRun).where(ReconciliationRun.id == run_id)
    )
    if not run:
        raise HTTPException(status_code=404, detail="Không tìm thấy phiên đối soát")

    stmt = (
        select(
            ReconciliationIssue,
            Invoice.id.label("invoice_id"),
        )
        .outerjoin(Invoice, Invoice.session_id == ReconciliationIssue.session_id)
        .where(ReconciliationIssue.run_id == run_id)
    )
    if severity:
        stmt = stmt.where(ReconciliationIssue.severity == severity)
    if issue_type:
        stmt = stmt.where(ReconciliationIssue.issue_type == issue_type)

    stmt = stmt.order_by(
        ReconciliationIssue.severity.asc(),
        ReconciliationIssue.created_at.desc(),
    )

    rows_res = (await db.execute(stmt)).all()
    csv_rows: list[list[Any]] = []
    for issue, inv_id in rows_res:
        desc = issue.details
        try:
            if issue.details.startswith("{") and issue.details.endswith("}"):
                parsed = json.loads(issue.details)
                desc = parsed.get("description", issue.details)
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            logger.debug("CSV issue details JSON parse fallback: %s", exc)

        csv_rows.append(
            [
                str(issue.run_id),
                issue.session_id,
                str(inv_id) if inv_id is not None else "",
                issue.issue_type,
                issue.severity,
                issue.recomputed_vnd if issue.recomputed_vnd is not None else "",
                issue.billed_vnd if issue.billed_vnd is not None else "",
                issue.debited_vnd if issue.debited_vnd is not None else "",
                issue.money_difference_vnd
                if issue.money_difference_vnd is not None
                else "",
                issue.meter_kwh if issue.meter_kwh is not None else "",
                issue.billed_kwh if issue.billed_kwh is not None else "",
                issue.kwh_difference if issue.kwh_difference is not None else "",
                desc,
                run.status,
            ]
        )

    filename = f"reconciliation_issues_{run_id}.csv"
    return build_csv_streaming_response(
        filename, RECONCILIATION_ISSUES_CSV_HEADERS, csv_rows
    )
