"""Reconciliation service for S-53: audit energy vs billed and debited money."""

import hashlib
from datetime import UTC, date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import String, and_, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.accounting.models import ReconciliationIssue, ReconciliationRun
from src.modules.accounting.schemas import ReconciliationRunCreateRequest
from src.modules.billing.models import Invoice, InvoiceLine
from src.modules.charging.models import ChargingSession
from src.modules.identity.models import User
from src.modules.stations.models import ChargePoint, Connector, Station
from src.modules.wallet.models import Wallet, WalletLedger

REPORT_TIMEZONE = ZoneInfo("Asia/Ho_Chi_Minh")


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
    session_ids: list[int],
) -> str:
    content = (
        f"{date_from.isoformat()}_{date_to.isoformat()}_{station_id}_"
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

    # 1. Fetch relevant sessions (AC-7)
    # ended_at in bounds OR invoice.created_at in bounds OR ledger.created_at in bounds
    # Note: charging_debit uses reference_id == cast(session.id, String)
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

    # 3. Batch load invoice lines
    lines_by_invoice: dict[UUID, list[InvoiceLine]] = {}
    if invoice_ids:
        line_stmt = (
            select(InvoiceLine)
            .where(InvoiceLine.invoice_id.in_(invoice_ids))
            .order_by(InvoiceLine.started_at, InvoiceLine.id)
        )
        lines = (await db.scalars(line_stmt)).all()
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

    summary_counts: dict[str, int] = {
        "missing_invoice": 0,
        "missing_ledger": 0,
        "ledger_mismatch": 0,
        "pricing_mismatch": 0,
        "meter_missing": 0,
        "meter_decreased": 0,
        "meter_discrepancy": 0,
        "legacy_exempt": 0,
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
                        details="Thiếu số đo đồng hồ đầu (meterStart) hoặc cuối (meterStop) từ bản tin OCPP.",
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
                        details=f"Số đo đồng hồ bị giảm bất thường (Bắt đầu: {meter_start} Wh, Kết thúc: {meter_stop} Wh).",
                    )
                )
            else:
                sess_meter_wh = Decimal(meter_stop - meter_start)
                sess_meter_kwh = sess_meter_wh / Decimal(1000)
                total_meter_kwh += sess_meter_kwh

        # --- B. Invoice Existence & Verification (AC-2) ---
        if invoice is None:
            if charging.ended_at is not None:
                # Check if awaiting unplug
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
                            details="Phiên sạc đã kết thúc nhưng chưa có hoá đơn được tạo trong hệ thống.",
                        )
                    )
        else:
            # Invoice exists
            inv_total = invoice.total_vnd
            total_billed_vnd += inv_total

            # 1. Ledger Verification (AC-2)
            debited = 0
            if inv_total == 0:
                # Valid zero invoice
                pass
            elif charging.settlement_reason == "legacy_exempt":
                summary_counts["legacy_exempt"] += 1
                summary_counts["info"] += 1
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
                            details="Hoá đơn có số tiền > 0 nhưng không tìm thấy dòng trừ ví (charging_debit) trong sổ cái.",
                        )
                    )
                else:
                    # Check wallet driver & ledger amount
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
                                details="; ".join(mismatch_details),
                            )
                        )

            # 2. Pure Price Recomputation (AC-3, AC-5)
            lines = lines_by_invoice.get(invoice.id, [])
            recomputed_session_vnd = 0
            lines_billed_wh = Decimal(0)

            for line in lines:
                if line.line_type == "energy":
                    energy_wh = Decimal(line.energy_wh)
                    lines_billed_wh += energy_wh
                    rate_vnd = Decimal(line.rate_vnd)
                    # Rounding rule: half-up to integer dong per segment
                    expected_vnd = int(
                        (energy_wh * rate_vnd / Decimal(1000)).quantize(
                            Decimal(1), rounding=ROUND_HALF_UP
                        )
                    )
                    recomputed_session_vnd += expected_vnd
                elif line.line_type == "idle":
                    recomputed_session_vnd += line.amount_vnd

            total_recomputed_vnd += recomputed_session_vnd
            sess_billed_kwh = lines_billed_wh / Decimal(1000)
            total_billed_kwh += sess_billed_kwh

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
                        details=(
                            f"Số tiền hoá đơn ({inv_total} đ) lệch so với tính toán lại "
                            f"từ biểu giá và quy tắc làm tròn ({recomputed_session_vnd} đ), chênh {diff_money} đ."
                        ),
                    )
                )

            # 3. Energy Meter vs Billed Line Comparison (AC-4, AC-5)
            if sess_meter_wh is not None:
                wh_diff = abs(sess_meter_wh - lines_billed_wh)
                if wh_diff > Decimal("0.001"):  # Wh precision check
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
                            details=(
                                f"Điện năng đồng hồ ({sess_meter_wh} Wh) lệch với tổng điện năng "
                                f"trên các dòng hoá đơn ({lines_billed_wh} Wh), chênh lệch {wh_diff} Wh."
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
    input_hash = calculate_input_hash(
        request.date_from,
        request.date_to,
        request.station_id,
        cutoff_at,
        list(session_map.keys()),
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
    return await db.scalar(
        select(ReconciliationRun).where(ReconciliationRun.id == run_id)
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
                "issue_type": issue.issue_type,
                "severity": issue.severity,
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
                "details": issue.details,
                "created_at": issue.created_at,
            }
        )

    return items, total
