from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from src.modules.reporting.schemas import (
    RevenueReportQuery,
    RevenueReportResponse,
)
from src.modules.reporting.service import (
    REPORT_TIMEZONE,
    get_revenue_report,
    resolve_report_range,
)


@dataclass
class MockInvoicedRow:
    invoice_id: UUID
    session_id: UUID
    invoice_created_at: datetime
    invoice_total_vnd: int
    station_id: UUID
    station_name: str
    charge_point_id: UUID
    charge_point_code: str
    energy_wh: Decimal
    energy_amount_vnd: int
    idle_amount_vnd: int
    debited_vnd: int


@dataclass
class MockUnbilledRow:
    session_id: UUID
    station_id: UUID
    station_name: str
    charge_point_id: UUID
    charge_point_code: str
    ended_at: datetime
    energy_kwh: Decimal


def create_mock_db(
    invoiced_rows: list[MockInvoicedRow] | None = None,
    unbilled_rows: list[MockUnbilledRow] | None = None,
) -> AsyncMock:
    db = AsyncMock()
    mock_inv_res = MagicMock()
    mock_inv_res.all.return_value = invoiced_rows or []

    mock_unbilled_res = MagicMock()
    mock_unbilled_res.all.return_value = unbilled_rows or []

    db.execute.side_effect = [mock_inv_res, mock_unbilled_res]
    return db


# =====================================================================
# 1. Pure Range Resolver Tests
# =====================================================================
def test_resolve_report_range_day() -> None:
    target = date(2026, 11, 5)
    start_dt, end_dt = resolve_report_range("day", date_from=target)
    assert start_dt == datetime(2026, 11, 5, 0, 0, 0, tzinfo=REPORT_TIMEZONE)
    assert end_dt == datetime(2026, 11, 6, 0, 0, 0, tzinfo=REPORT_TIMEZONE)


def test_resolve_report_range_week() -> None:
    # 2026-11-04 is Wednesday
    target = date(2026, 11, 4)
    start_dt, end_dt = resolve_report_range("week", date_from=target)
    # Monday is 2026-11-02
    assert start_dt == datetime(2026, 11, 2, 0, 0, 0, tzinfo=REPORT_TIMEZONE)
    assert end_dt == datetime(2026, 11, 9, 0, 0, 0, tzinfo=REPORT_TIMEZONE)


def test_resolve_report_range_month() -> None:
    target = date(2026, 11, 15)
    start_dt, end_dt = resolve_report_range("month", date_from=target)
    assert start_dt == datetime(2026, 11, 1, 0, 0, 0, tzinfo=REPORT_TIMEZONE)
    assert end_dt == datetime(2026, 12, 1, 0, 0, 0, tzinfo=REPORT_TIMEZONE)


def test_resolve_report_range_month_december() -> None:
    target = date(2026, 12, 20)
    start_dt, end_dt = resolve_report_range("month", date_from=target)
    assert start_dt == datetime(2026, 12, 1, 0, 0, 0, tzinfo=REPORT_TIMEZONE)
    assert end_dt == datetime(2027, 1, 1, 0, 0, 0, tzinfo=REPORT_TIMEZONE)


def test_resolve_report_range_custom() -> None:
    d_from = date(2026, 10, 10)
    d_to = date(2026, 10, 15)
    start_dt, end_dt = resolve_report_range("custom", date_from=d_from, date_to=d_to)
    assert start_dt == datetime(2026, 10, 10, 0, 0, 0, tzinfo=REPORT_TIMEZONE)
    assert end_dt == datetime(2026, 10, 16, 0, 0, 0, tzinfo=REPORT_TIMEZONE)


# =====================================================================
# 2. Schema Validation Tests
# =====================================================================
def test_query_validation_date_order() -> None:
    with pytest.raises(ValidationError):
        RevenueReportQuery(
            period="custom",
            date_from=date(2026, 11, 20),
            date_to=date(2026, 11, 10),
        )


def test_query_validation_page_limits() -> None:
    with pytest.raises(ValidationError):
        RevenueReportQuery(page=0)

    with pytest.raises(ValidationError):
        RevenueReportQuery(page_size=150)


# =====================================================================
# 3. Aggregation & Business Invariant Tests (AC-1 to AC-7)
# =====================================================================
@pytest.mark.asyncio
async def test_multiline_invoice_does_not_duplicate_sessions() -> None:
    """AC-6 & Ca nghiệm thu 3: 1 hóa đơn với nhiều dòng chi tiết chỉ tính 1 phiên."""
    station_id = uuid4()
    cp_id = uuid4()
    inv_created = datetime(2026, 11, 10, 10, 0, 0, tzinfo=REPORT_TIMEZONE)

    # 1 invoice aggregating 2 energy lines + 1 idle fee line
    row = MockInvoicedRow(
        invoice_id=uuid4(),
        session_id=uuid4(),
        invoice_created_at=inv_created,
        invoice_total_vnd=125000,
        station_id=station_id,
        station_name="Trạm Quận 1",
        charge_point_id=cp_id,
        charge_point_code="CP-01",
        energy_wh=Decimal(35000),
        energy_amount_vnd=112500,
        idle_amount_vnd=12500,
        debited_vnd=125000,
    )

    db = create_mock_db([row], [])
    query = RevenueReportQuery(period="month", date_from=date(2026, 11, 1))
    report: RevenueReportResponse = await get_revenue_report(
        db, query, owner_id=uuid4()
    )

    # Exactly 1 invoiced session
    assert report.summary.invoiced_sessions == 1
    assert report.summary.total_kwh == Decimal("35.0")
    assert report.summary.energy_amount_vnd == 112500
    assert report.summary.idle_amount_vnd == 12500
    assert report.summary.total_invoice_vnd == 125000
    assert report.summary.debited_vnd == 125000
    assert report.summary.awaiting_settlement_vnd == 0

    # Charge point breakdown
    assert len(report.charge_points) == 1
    cp_item = report.charge_points[0]
    assert cp_item.charge_point_id == cp_id
    assert cp_item.sessions_count == 1
    assert cp_item.energy_kwh == Decimal("35.0")
    assert cp_item.total_invoice_vnd == 125000


@pytest.mark.asyncio
async def test_cross_month_session_revenue_cohort() -> None:
    """AC-2 & Ca nghiệm thu 1: Phiên sạc bắt đầu cuối tháng 10, hóa đơn tạo đầu tháng 11."""
    station_id = uuid4()
    cp_id = uuid4()
    inv_created_nov = datetime(2026, 11, 1, 0, 20, 0, tzinfo=REPORT_TIMEZONE)

    row = MockInvoicedRow(
        invoice_id=uuid4(),
        session_id=uuid4(),
        invoice_created_at=inv_created_nov,
        invoice_total_vnd=38500,
        station_id=station_id,
        station_name="Trạm Quận 7",
        charge_point_id=cp_id,
        charge_point_code="CP-02",
        energy_wh=Decimal(10000),
        energy_amount_vnd=38500,
        idle_amount_vnd=0,
        debited_vnd=38500,
    )

    # When querying November, the row is returned by query
    db = create_mock_db([row], [])
    query_nov = RevenueReportQuery(period="month", date_from=date(2026, 11, 15))
    report_nov = await get_revenue_report(db, query_nov, owner_id=uuid4())

    assert report_nov.summary.invoiced_sessions == 1
    assert report_nov.summary.total_invoice_vnd == 38500
    assert report_nov.summary.total_kwh == Decimal("10.0")

    # When querying October, no row returned
    db_oct = create_mock_db([], [])
    query_oct = RevenueReportQuery(period="month", date_from=date(2026, 10, 15))
    report_oct = await get_revenue_report(db_oct, query_oct, owner_id=uuid4())

    assert report_oct.summary.invoiced_sessions == 0
    assert report_oct.summary.total_invoice_vnd == 0
    assert report_oct.summary.total_kwh == Decimal(0)


@pytest.mark.asyncio
async def test_awaiting_settlement_computation() -> None:
    """AC-3 & Ca nghiệm thu 4: Hóa đơn chưa thu tiền hiển thị awaiting_settlement_vnd."""
    station_id = uuid4()
    cp_id = uuid4()
    inv_created = datetime(2026, 11, 14, 16, 0, 0, tzinfo=REPORT_TIMEZONE)

    row = MockInvoicedRow(
        invoice_id=uuid4(),
        session_id=uuid4(),
        invoice_created_at=inv_created,
        invoice_total_vnd=100000,
        station_id=station_id,
        station_name="Trạm Thủ Đức",
        charge_point_id=cp_id,
        charge_point_code="CP-03",
        energy_wh=Decimal(15000),
        energy_amount_vnd=100000,
        idle_amount_vnd=0,
        debited_vnd=40000,  # Only 40,000 VND debited
    )

    db = create_mock_db([row], [])
    query = RevenueReportQuery(period="month", date_from=date(2026, 11, 1))
    report = await get_revenue_report(db, query, owner_id=uuid4())

    assert report.summary.total_invoice_vnd == 100000
    assert report.summary.debited_vnd == 40000
    assert report.summary.awaiting_settlement_vnd == 60000

    cp_item = report.charge_points[0]
    assert cp_item.total_invoice_vnd == 100000
    assert cp_item.debited_vnd == 40000
    assert cp_item.awaiting_settlement_vnd == 60000


@pytest.mark.asyncio
async def test_unbilled_operating_sessions_separated() -> None:
    """AC-5: Phiên hoàn tất chưa xuất hóa đơn được tách riêng sản lượng vận hành."""
    station_id = uuid4()
    cp_id = uuid4()
    ended_nov = datetime(2026, 11, 18, 12, 0, 0, tzinfo=REPORT_TIMEZONE)

    unbilled_row = MockUnbilledRow(
        session_id=uuid4(),
        station_id=station_id,
        station_name="Trạm Tân Bình",
        charge_point_id=cp_id,
        charge_point_code="CP-04",
        ended_at=ended_nov,
        energy_kwh=Decimal("25.5"),
    )

    db = create_mock_db([], [unbilled_row])
    query = RevenueReportQuery(period="month", date_from=date(2026, 11, 1))
    report = await get_revenue_report(db, query, owner_id=uuid4())

    assert report.summary.invoiced_sessions == 0
    assert report.summary.total_invoice_vnd == 0
    assert report.summary.unbilled_sessions == 1
    assert report.summary.unbilled_operating_kwh == Decimal("25.5")

    assert len(report.charge_points) == 1
    cp_item = report.charge_points[0]
    assert cp_item.unbilled_sessions == 1
    assert cp_item.unbilled_operating_kwh == Decimal("25.5")
    assert cp_item.total_invoice_vnd == 0


@pytest.mark.asyncio
async def test_daily_timeline_generation() -> None:
    """AC-6: Biểu đồ theo ngày hiển thị đúng từng ngày trong kỳ."""
    station_id = uuid4()
    cp_id = uuid4()

    # Two invoices on different days
    row1 = MockInvoicedRow(
        invoice_id=uuid4(),
        session_id=uuid4(),
        invoice_created_at=datetime(2026, 11, 2, 8, 0, 0, tzinfo=REPORT_TIMEZONE),
        invoice_total_vnd=50000,
        station_id=station_id,
        station_name="Trạm",
        charge_point_id=cp_id,
        charge_point_code="CP-01",
        energy_wh=Decimal(15000),
        energy_amount_vnd=50000,
        idle_amount_vnd=0,
        debited_vnd=50000,
    )
    row2 = MockInvoicedRow(
        invoice_id=uuid4(),
        session_id=uuid4(),
        invoice_created_at=datetime(2026, 11, 3, 14, 0, 0, tzinfo=REPORT_TIMEZONE),
        invoice_total_vnd=70000,
        station_id=station_id,
        station_name="Trạm",
        charge_point_id=cp_id,
        charge_point_code="CP-01",
        energy_wh=Decimal(20000),
        energy_amount_vnd=70000,
        idle_amount_vnd=0,
        debited_vnd=70000,
    )

    db = create_mock_db([row1, row2], [])
    query = RevenueReportQuery(
        period="custom",
        date_from=date(2026, 11, 1),
        date_to=date(2026, 11, 4),
    )
    report = await get_revenue_report(db, query, owner_id=uuid4())

    # Range [2026-11-01, 2026-11-05): 4 days in timeline
    assert len(report.daily_timeline) == 4
    dates = [d.date for d in report.daily_timeline]
    assert dates == ["2026-11-01", "2026-11-02", "2026-11-03", "2026-11-04"]

    assert report.daily_timeline[0].sessions_count == 0
    assert report.daily_timeline[0].invoice_vnd == 0

    assert report.daily_timeline[1].sessions_count == 1
    assert report.daily_timeline[1].invoice_vnd == 50000
    assert report.daily_timeline[1].kwh == Decimal("15.0")

    assert report.daily_timeline[2].sessions_count == 1
    assert report.daily_timeline[2].invoice_vnd == 70000
    assert report.daily_timeline[2].kwh == Decimal("20.0")

    assert report.daily_timeline[3].sessions_count == 0


@pytest.mark.asyncio
async def test_charge_point_sorting_and_pagination() -> None:
    """AC-6 & NFR-2: Sắp xếp theo doanh thu giảm dần và phân trang chính xác."""
    station_id = uuid4()
    cp1_id = uuid4()
    cp2_id = uuid4()
    cp3_id = uuid4()
    now = datetime(2026, 11, 5, 10, 0, 0, tzinfo=REPORT_TIMEZONE)

    row1 = MockInvoicedRow(
        invoice_id=uuid4(),
        session_id=uuid4(),
        invoice_created_at=now,
        invoice_total_vnd=30000,  # rank 2
        station_id=station_id,
        station_name="Trạm",
        charge_point_id=cp1_id,
        charge_point_code="CP-01",
        energy_wh=Decimal(10000),
        energy_amount_vnd=30000,
        idle_amount_vnd=0,
        debited_vnd=30000,
    )
    row2 = MockInvoicedRow(
        invoice_id=uuid4(),
        session_id=uuid4(),
        invoice_created_at=now,
        invoice_total_vnd=100000,  # rank 1
        station_id=station_id,
        station_name="Trạm",
        charge_point_id=cp2_id,
        charge_point_code="CP-02",
        energy_wh=Decimal(30000),
        energy_amount_vnd=100000,
        idle_amount_vnd=0,
        debited_vnd=100000,
    )
    row3 = MockInvoicedRow(
        invoice_id=uuid4(),
        session_id=uuid4(),
        invoice_created_at=now,
        invoice_total_vnd=10000,  # rank 3
        station_id=station_id,
        station_name="Trạm",
        charge_point_id=cp3_id,
        charge_point_code="CP-03",
        energy_wh=Decimal(5000),
        energy_amount_vnd=10000,
        idle_amount_vnd=0,
        debited_vnd=10000,
    )

    db = create_mock_db([row1, row2, row3], [])
    # Page size 2
    query = RevenueReportQuery(
        period="month",
        date_from=date(2026, 11, 1),
        page=1,
        page_size=2,
    )
    report = await get_revenue_report(db, query, owner_id=uuid4())

    assert report.pagination.total_items == 3
    assert report.pagination.total_pages == 2
    assert report.pagination.page == 1
    assert len(report.charge_points) == 2

    # First item must be CP-02 (100k), second CP-01 (30k)
    assert report.charge_points[0].charge_point_id == cp2_id
    assert report.charge_points[1].charge_point_id == cp1_id

    # Summary has full totals before pagination
    assert report.summary.total_invoice_vnd == 140000
    assert report.summary.invoiced_sessions == 3
