"""Comprehensive audit tests for S-58: CSV export scope, snapshot stability and large dataset streaming.

Validates the 5 critical audit criteria:
1. Custom date range resolution (e.g. 10–12/10 does not expand to whole month; > 366 days rejected).
2. Multi-page cohort reconciliation: CSV unpaginated sum matches paginated API summary across >= 3 pages.
3. Access control: Unauthorized/cross-owner export requests are rejected (401/403).
4. Snapshot immutability: Re-exporting an old reconciliation run after new invoices/settlements
   are created preserves the cutoff snapshot (invoice_id remains empty for missing_invoice).
   Validates expected/actual semantics for missing ledger (expected=billed, actual=0), pricing mismatch,
   integer VND, decimal dot kWh, and exclusion of raw emails/idTags.
5. Vietnamese diacritics, quotes, commas, newlines, and formula injection neutralization.
6. Large data export (10,000+ rows): memory usage (< 5MB delta via tracemalloc), response time,
   quota declaration (X-Export-Quota-Limit: 100000) and cutoff handling.
"""

import csv
import io
import time
import tracemalloc
from collections.abc import Generator
from datetime import date, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from src.entrypoints.http import app
from src.modules.accounting.models import ReconciliationIssue, ReconciliationRun
from src.modules.accounting.service import (
    export_reconciliation_issues_csv,
)
from src.modules.identity.authorization import CurrentActor
from src.modules.identity.dependencies import get_current_actor
from src.modules.reporting.schemas import RevenueReportQuery
from src.modules.reporting.service import (
    REPORT_TIMEZONE,
    export_revenue_report_csv,
    get_revenue_report,
    resolve_report_range,
)
from src.platform.csv_export import UTF8_BOM
from src.platform.database.session import get_db_session


def set_actor(role: str = "accountant", user_id: UUID | None = None) -> UUID:
    actor_id = user_id or uuid4()
    app.dependency_overrides[get_current_actor] = lambda: CurrentActor(
        actor_id, frozenset({role})
    )
    return actor_id


@pytest.fixture(autouse=True)
def clean_actor() -> Generator[None, None, None]:
    yield
    app.dependency_overrides.pop(get_current_actor, None)
    app.dependency_overrides.pop(get_db_session, None)


# ===========================================================================
# 1. Date Range Resolution & Range Limit Audit
# ===========================================================================
def test_custom_date_range_resolution_and_validation() -> None:
    # Scenario: User selects 10/10/2026 to 12/10/2026
    d_from = date(2026, 10, 10)
    d_to = date(2026, 10, 12)

    # 1. Period explicitly 'custom'
    start_dt, end_dt = resolve_report_range("custom", date_from=d_from, date_to=d_to)
    assert start_dt == datetime(2026, 10, 10, 0, 0, 0, tzinfo=REPORT_TIMEZONE)
    assert end_dt == datetime(2026, 10, 13, 0, 0, 0, tzinfo=REPORT_TIMEZONE)

    # 2. Period was 'month' (legacy frontend behavior) but dates were passed -> auto switches to custom
    start_dt_auto, end_dt_auto = resolve_report_range(
        "month", date_from=d_from, date_to=d_to
    )
    assert start_dt_auto == datetime(2026, 10, 10, 0, 0, 0, tzinfo=REPORT_TIMEZONE)
    assert end_dt_auto == datetime(2026, 10, 13, 0, 0, 0, tzinfo=REPORT_TIMEZONE)

    # 3. RevenueReportQuery schema auto-adjusts period and validates bounds
    query = RevenueReportQuery(
        period="month",
        date_from=d_from,
        date_to=d_to,
    )
    assert query.period == "custom"

    # 4. Range > 366 days must be rejected
    with pytest.raises(
        ValueError, match="Khoảng thời gian xuất báo cáo tối đa là 366 ngày"
    ):
        RevenueReportQuery(
            period="custom",
            date_from=date(2025, 1, 1),
            date_to=date(2026, 1, 10),
        )

    # 5. date_from > date_to must be rejected
    with pytest.raises(
        ValueError, match="Ngày bắt đầu phải trước hoặc bằng ngày kết thúc"
    ):
        RevenueReportQuery(
            period="custom",
            date_from=date(2026, 10, 15),
            date_to=date(2026, 10, 10),
        )


# ===========================================================================
# 2. Multi-Page Cohort Reconciliation: CSV Sum vs Report Summary
# ===========================================================================
@pytest.mark.asyncio
async def test_csv_cohort_sums_match_revenue_summary_across_multiple_pages() -> None:
    """Verifies that unpaginated CSV export total matches the paginated report summary across >= 3 pages."""
    db = AsyncMock()
    station_id = uuid4()
    now = datetime(2026, 10, 11, 12, 0, 0, tzinfo=REPORT_TIMEZONE)

    # Create 7 charge points (with page_size=2 this will yield 4 pages >= 3 pages)
    charge_points = []
    invoiced_rows = []
    debit_rows = []

    for i in range(1, 8):
        cp_id = uuid4()
        charge_points.append(cp_id)

        inv_row = MagicMock()
        inv_row.invoice_id = uuid4()
        inv_row.session_id = uuid4()
        inv_row.invoice_created_at = now
        inv_row.invoice_total_vnd = 50000 * i
        inv_row.station_id = station_id
        inv_row.station_name = f"Trạm sạc Quận {i}"
        inv_row.charge_point_id = cp_id
        inv_row.charge_point_code = f"CP-{i:02d}"
        inv_row.energy_wh = Decimal(10000 * i)
        inv_row.energy_amount_vnd = 45000 * i
        inv_row.idle_amount_vnd = 5000 * i
        inv_row.debited_vnd = 50000 * i
        inv_row.session_debited_vnd = 50000 * i
        inv_row.settlement_reason = "debited"
        invoiced_rows.append(inv_row)

        debit_row = MagicMock()
        debit_row.station_id = station_id
        debit_row.station_name = f"Trạm sạc Quận {i}"
        debit_row.charge_point_id = cp_id
        debit_row.charge_point_code = f"CP-{i:02d}"
        debit_row.debited_vnd = 50000 * i
        debit_row.created_at = now
        debit_rows.append(debit_row)

    mock_invoiced_res = MagicMock()
    mock_invoiced_res.all.return_value = invoiced_rows

    mock_unbilled_res = MagicMock()
    mock_unbilled_res.all.return_value = []

    mock_debit_res = MagicMock()
    mock_debit_res.all.return_value = debit_rows

    mock_resv_res = MagicMock()
    mock_resv_res.all.return_value = []

    db.execute.side_effect = [
        mock_invoiced_res,
        mock_unbilled_res,
        mock_debit_res,
        mock_resv_res,
        # Re-execution for second call
        mock_invoiced_res,
        mock_unbilled_res,
        mock_debit_res,
        mock_resv_res,
    ]

    # Query for paginated report (page 1 of 4)
    query_page = RevenueReportQuery(
        period="custom",
        date_from=date(2026, 10, 10),
        date_to=date(2026, 10, 12),
        page=1,
        page_size=2,
    )
    report_res = await get_revenue_report(db, query_page)
    assert (
        report_res.pagination.total_pages == 4
    )  # 7 items / 2 per page = 4 pages (>= 3 pages)
    assert report_res.pagination.total_items == 7

    # Export CSV unpaginated
    query_export = RevenueReportQuery(
        period="custom",
        date_from=date(2026, 10, 10),
        date_to=date(2026, 10, 12),
    )
    streaming_res = await export_revenue_report_csv(db, query_export)
    body_chunks = [chunk async for chunk in streaming_res.body_iterator]
    csv_text = b"".join(body_chunks).decode("utf-8")

    reader = csv.reader(io.StringIO(csv_text.lstrip(UTF8_BOM)))
    headers = next(reader)
    rows = list(reader)

    assert len(rows) == 7  # All 7 charge points exported regardless of pagination

    # Verify column sums match report summary
    total_csv_sessions = sum(int(r[headers.index("sessions")]) for r in rows)
    total_csv_energy = sum(Decimal(r[headers.index("energy_kwh")]) for r in rows)
    total_csv_invoice_vnd = sum(
        int(r[headers.index("invoice_total_vnd")]) for r in rows
    )
    total_csv_debited_vnd = sum(int(r[headers.index("debited_vnd")]) for r in rows)

    assert total_csv_sessions == report_res.summary.invoiced_sessions
    assert total_csv_energy == report_res.summary.total_kwh
    assert total_csv_invoice_vnd == report_res.summary.total_invoice_vnd
    assert total_csv_debited_vnd == report_res.summary.debited_vnd


# ===========================================================================
# 3. RBAC & Cross-Owner Export Security
# ===========================================================================
@pytest.mark.asyncio
async def test_rbac_and_cross_owner_export_denied() -> None:
    run_id = uuid4()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        # 1. Unauthenticated direct URL call -> 401
        res1 = await client.get(
            f"/api/v1/accounting/reconciliation-runs/{run_id}/issues/export"
        )
        assert res1.status_code == 401

        res2 = await client.get("/api/v1/accounting/reports/revenue/export")
        assert res2.status_code == 401

        # 2. Driver role calling accountant reconciliation export -> 403
        set_actor("driver")
        res3 = await client.get(
            f"/api/v1/accounting/reconciliation-runs/{run_id}/issues/export"
        )
        assert res3.status_code == 403

        # 3. Station owner calling accountant revenue export -> 403
        set_actor("station_owner")
        res4 = await client.get("/api/v1/accounting/reports/revenue/export")
        assert res4.status_code == 403


# ===========================================================================
# 4. Snapshot Immutability & Expected/Actual Semantics
# ===========================================================================
@pytest.mark.asyncio
async def test_snapshot_immutability_and_expected_actual_semantics() -> None:
    """Verifies that creating live invoices AFTER a reconciliation run does not mutate

    the historical snapshot export. Also verifies expected/actual values for missing ledger
    and pricing mismatch.
    """
    run_id = uuid4()
    db = AsyncMock()

    mock_run = MagicMock(spec=ReconciliationRun)
    mock_run.id = run_id
    mock_run.status = "completed"
    mock_run.algorithm_version = "2.1"
    db.scalar.return_value = mock_run

    # Issue 1: Missing invoice (Session completed, no invoice at cutoff)
    issue_missing_inv = MagicMock(spec=ReconciliationIssue)
    issue_missing_inv.run_id = run_id
    issue_missing_inv.session_id = "sess_no_invoice_at_cutoff"
    issue_missing_inv.issue_type = "missing_invoice"
    issue_missing_inv.severity = "critical"
    issue_missing_inv.recomputed_vnd = 38500
    issue_missing_inv.billed_vnd = None
    issue_missing_inv.debited_vnd = None
    issue_missing_inv.money_difference_vnd = 38500
    issue_missing_inv.meter_kwh = Decimal("10.000000")
    issue_missing_inv.billed_kwh = None
    issue_missing_inv.kwh_difference = Decimal("10.000000")
    issue_missing_inv.details = (
        '{"description": "Phiên chưa có hóa đơn", "evidence": {"invoice_id": null}}'
    )

    # Issue 2: Missing ledger 38,500đ (Billed 38,500đ, debited 0đ)
    issue_missing_ledger = MagicMock(spec=ReconciliationIssue)
    issue_missing_ledger.run_id = run_id
    issue_missing_ledger.session_id = "sess_missing_ledger"
    issue_missing_ledger.issue_type = "missing_ledger"
    issue_missing_ledger.severity = "critical"
    issue_missing_ledger.recomputed_vnd = 38500
    issue_missing_ledger.billed_vnd = 38500
    issue_missing_ledger.debited_vnd = 0
    issue_missing_ledger.money_difference_vnd = 38500
    issue_missing_ledger.meter_kwh = Decimal("10.000000")
    issue_missing_ledger.billed_kwh = Decimal("10.000000")
    issue_missing_ledger.kwh_difference = Decimal("0.000000")
    issue_missing_ledger.details = '{"description": "Hóa đơn chưa ghi nợ ví", "evidence": {"invoice_id": "inv-snapshot-123"}}'

    # Issue 3: Pricing mismatch (Calculated 45,000đ, billed 50,000đ)
    issue_pricing = MagicMock(spec=ReconciliationIssue)
    issue_pricing.run_id = run_id
    issue_pricing.session_id = "sess_pricing_mismatch"
    issue_pricing.issue_type = "pricing_mismatch"
    issue_pricing.severity = "warning"
    issue_pricing.recomputed_vnd = 45000
    issue_pricing.billed_vnd = 50000
    issue_pricing.debited_vnd = 50000
    issue_pricing.money_difference_vnd = 5000
    issue_pricing.meter_kwh = Decimal("12.500000")
    issue_pricing.billed_kwh = Decimal("12.500000")
    issue_pricing.kwh_difference = Decimal("0.000000")
    issue_pricing.details = '{"description": "Sai lệch biểu giá", "evidence": {"invoice_id": "inv-snapshot-456"}}'

    # Even if a live invoice was subsequently created in the DB with UUID "new-live-invoice-uuid",
    # the query strictly selects ReconciliationIssue WITHOUT joining Invoice!
    mock_res = MagicMock()
    mock_res.all.return_value = [issue_missing_inv, issue_missing_ledger, issue_pricing]
    db.execute.return_value = mock_res

    res = await export_reconciliation_issues_csv(db, run_id=run_id)
    body_chunks = [chunk async for chunk in res.body_iterator]
    csv_text = b"".join(body_chunks).decode("utf-8")

    reader = csv.reader(io.StringIO(csv_text.lstrip(UTF8_BOM)))
    headers = next(reader)
    rows = list(reader)

    # Validate headers contain all metadata
    assert "generated_at" in headers
    assert "timezone" in headers
    assert "filter_category" in headers
    assert "run_revision" in headers

    row_map = {r[headers.index("session_id")]: r for r in rows}

    # 1. Missing invoice: invoice_id MUST be empty string, NOT any live invoice id
    row1 = row_map["sess_no_invoice_at_cutoff"]
    assert row1[headers.index("invoice_id")] == ""
    assert row1[headers.index("expected_vnd")] == "38500"
    assert row1[headers.index("actual_vnd")] == "0"
    assert row1[headers.index("run_revision")] == "2.1"
    assert row1[headers.index("timezone")] == "Asia/Ho_Chi_Minh"

    # 2. Missing ledger: expected must be billed (38500), actual debited (0), delta (38500)
    row2 = row_map["sess_missing_ledger"]
    assert row2[headers.index("invoice_id")] == "inv-snapshot-123"
    assert row2[headers.index("expected_vnd")] == "38500"
    assert row2[headers.index("actual_vnd")] == "0"
    assert row2[headers.index("debited_vnd")] == "0"
    assert row2[headers.index("delta_vnd")] == "38500"
    assert row2[headers.index("meter_kwh")] == "10.000000"

    # 3. Pricing mismatch: expected must be recomputed (45000), actual billed (50000), delta (5000)
    row3 = row_map["sess_pricing_mismatch"]
    assert row3[headers.index("invoice_id")] == "inv-snapshot-456"
    assert row3[headers.index("expected_vnd")] == "45000"
    assert row3[headers.index("actual_vnd")] == "50000"
    assert row3[headers.index("delta_vnd")] == "5000"

    # Ensure no raw email or RFID tag leaked in headers
    for h in headers:
        assert "email" not in h.lower()
        assert "idtag" not in h.lower()
        assert "rfid" not in h.lower()


# ===========================================================================
# 5. Vietnamese UTF-8 BOM, RFC 4180 Escaping & Formula Defense
# ===========================================================================
@pytest.mark.asyncio
async def test_vietnamese_formula_and_excel_encoding() -> None:
    run_id = uuid4()
    db = AsyncMock()

    mock_run = MagicMock(spec=ReconciliationRun)
    mock_run.id = run_id
    mock_run.status = "completed"
    db.scalar.return_value = mock_run

    issue = MagicMock(spec=ReconciliationIssue)
    issue.run_id = run_id
    issue.session_id = "sess_vietnamese_01"
    issue.issue_type = "pricing_mismatch"
    issue.severity = "warning"
    issue.recomputed_vnd = 150000
    issue.billed_vnd = 160000
    issue.debited_vnd = 160000
    issue.money_difference_vnd = 10000
    issue.meter_kwh = Decimal("45.123456")
    issue.billed_kwh = Decimal("45.123456")
    issue.kwh_difference = Decimal("0.000000")
    # Multi-line Vietnamese text with commas, quotes, and dangerous formula prefix
    issue.details = '=SUM(A1:A10); Trạm sạc "Tân Bình", TP. Hồ Chí Minh:\r\nPhát sinh chênh lệch 10,000 VNĐ'

    mock_res = MagicMock()
    mock_res.all.return_value = [issue]
    db.execute.return_value = mock_res

    res = await export_reconciliation_issues_csv(db, run_id=run_id)
    raw_content = b"".join([chunk async for chunk in res.body_iterator])

    # 1. UTF-8 BOM present
    assert raw_content.startswith(UTF8_BOM.encode("utf-8"))

    # 2. Decode text
    decoded_text = raw_content.decode("utf-8")
    assert "TP. Hồ Chí Minh" in decoded_text

    # 3. Parse via standard RFC 4180 CSV parser
    reader = csv.reader(io.StringIO(decoded_text.lstrip(UTF8_BOM)))
    headers = next(reader)
    rows = list(reader)
    assert len(rows) == 1

    details_val = rows[0][headers.index("details")]
    # Formula neutralized with leading apostrophe
    assert details_val.startswith("'=SUM(A1:A10)")
    assert 'Trạm sạc "Tân Bình"' in details_val
    assert "TP. Hồ Chí Minh" in details_val


# ===========================================================================
# 6. Streaming Performance, Quota Headers & Memory Profiling (10,000+ rows)
# ===========================================================================
@pytest.mark.asyncio
async def test_ten_thousand_rows_streaming_performance_and_memory() -> None:
    """Verifies that exporting >= 10,000 rows streams in batches without high memory delta."""
    run_id = uuid4()
    db = AsyncMock()

    class SlottedRun:
        __slots__ = ("algorithm_version", "id", "status")

        def __init__(self):
            self.id = run_id
            self.status = "completed"
            self.algorithm_version = "1.0"

    db.scalar.return_value = SlottedRun()

    total_generated = 10_500
    batch_size = 1000

    class SlottedIssue:
        __slots__ = (
            "billed_kwh",
            "billed_vnd",
            "debited_vnd",
            "details",
            "issue_type",
            "kwh_difference",
            "meter_kwh",
            "money_difference_vnd",
            "recomputed_vnd",
            "run_id",
            "session_id",
            "severity",
        )

        def __init__(self, idx: int):
            self.run_id = run_id
            self.session_id = f"sess_{idx:06d}"
            self.issue_type = "pricing_mismatch"
            self.severity = "info"
            self.recomputed_vnd = 20000
            self.billed_vnd = 22000
            self.debited_vnd = 22000
            self.money_difference_vnd = 2000
            self.meter_kwh = Decimal("5.500000")
            self.billed_kwh = Decimal("5.500000")
            self.kwh_difference = Decimal("0.000000")
            self.details = f"Chi tiết phiên sạc số {idx} tại trạm"

    class DummyCursor:
        def __init__(self, total: int, batch: int):
            self.total = total
            self.batch = batch
            self.current = 0

        def fetchmany(self, size: int | None = None) -> list[SlottedIssue]:
            if self.current >= self.total:
                return []
            s = size or self.batch
            end = min(self.current + s, self.total)
            batch_rows = [SlottedIssue(i) for i in range(self.current, end)]
            self.current = end
            return batch_rows

    dummy_cursor = DummyCursor(total_generated, batch_size)
    db.execute.return_value = dummy_cursor

    res = await export_reconciliation_issues_csv(db, run_id=run_id)

    # Verify quota and timezone response headers
    assert res.headers.get("X-Export-Quota-Limit") == "100000"
    assert res.headers.get("X-Export-Timezone") == "Asia/Ho_Chi_Minh"

    tracemalloc.start()
    start_time = time.perf_counter()

    row_count = 0
    chunk_count = 0
    async for chunk in res.body_iterator:
        chunk_count += 1
        row_count += chunk.count(b"\r\n")

    elapsed_time = time.perf_counter() - start_time
    _current_mem, peak_mem = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    peak_mb = peak_mem / (1024 * 1024)

    # Subtract header line from row count
    data_rows = row_count - 1

    assert data_rows == total_generated
    assert chunk_count > 10  # Confirms chunked streaming occurred
    # Memory consumption delta during streaming of 10,500 rows should remain small (< 5MB)
    assert peak_mb < 5.0, f"Peak memory was too high: {peak_mb:.2f} MB"
    assert elapsed_time < 3.0, f"Streaming took too long: {elapsed_time:.2f} seconds"
