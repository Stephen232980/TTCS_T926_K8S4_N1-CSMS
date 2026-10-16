"""Comprehensive tests for S-58: CSV export of revenue reports and reconciliation issues."""

from collections.abc import AsyncGenerator, Generator
from datetime import date, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from src.entrypoints.http import app
from src.modules.identity.authorization import CurrentActor
from src.modules.identity.dependencies import get_current_actor
from src.modules.reporting.schemas import RevenueReportQuery
from src.modules.reporting.service import (
    REPORT_TIMEZONE,
    REVENUE_CSV_HEADERS,
    export_revenue_report_csv,
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


# ---------------------------------------------------------------------------
# Unit tests for export_revenue_report_csv service function
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_export_revenue_report_csv_unpaginated_and_neutralized() -> None:
    db = AsyncMock()
    owner_id = uuid4()
    station_id = uuid4()
    cp1_id = uuid4()
    cp2_id = uuid4()
    now = datetime(2026, 11, 5, 10, 0, 0, tzinfo=REPORT_TIMEZONE)

    row1 = MagicMock()
    row1.invoice_id = uuid4()
    row1.session_id = uuid4()
    row1.invoice_created_at = now
    row1.invoice_total_vnd = 50000
    row1.station_id = station_id
    row1.station_name = "=SUM(A1:A10)"  # Potential CSV injection
    row1.charge_point_id = cp1_id
    row1.charge_point_code = "CP-01"
    row1.energy_wh = Decimal(15000)
    row1.energy_amount_vnd = 45000
    row1.idle_amount_vnd = 5000
    row1.debited_vnd = 50000

    row2 = MagicMock()
    row2.invoice_id = uuid4()
    row2.session_id = uuid4()
    row2.invoice_created_at = now
    row2.invoice_total_vnd = 100000
    row2.station_id = station_id
    row2.station_name = "=SUM(A1:A10)"
    row2.charge_point_id = cp2_id
    row2.charge_point_code = "@EVIL_CP"  # Potential CSV injection
    row2.energy_wh = Decimal(30000)
    row2.energy_amount_vnd = 90000
    row2.idle_amount_vnd = 10000
    row2.debited_vnd = 100000

    mock_inv_res = MagicMock()
    mock_inv_res.all.return_value = [row1, row2]

    mock_unbilled_res = MagicMock()
    mock_unbilled_res.all.return_value = []

    db.execute.side_effect = [mock_inv_res, mock_unbilled_res]

    query = RevenueReportQuery(
        period="month",
        date_from=date(2026, 11, 1),
        page=1,
        page_size=1,  # In UI page_size is 1, but CSV must be unpaginated (AC-4)
    )

    resp = await export_revenue_report_csv(db, query, owner_id=owner_id)
    assert resp.media_type == "text/csv; charset=utf-8"
    assert "revenue_report_" in resp.headers["Content-Disposition"]

    # Read streamed body
    chunks = []
    async for chunk in resp.body_iterator:
        chunks.append(chunk if isinstance(chunk, bytes) else chunk.encode("utf-8"))
    content = b"".join(chunks)

    # Check BOM
    assert content.startswith(UTF8_BOM.encode("utf-8"))

    decoded = content.decode("utf-8")
    lines = decoded.strip().split("\r\n")

    # Header line + 2 data rows (unpaginated: both CPs returned)
    assert len(lines) == 3
    assert lines[0].lstrip(UTF8_BOM) == ",".join(REVENUE_CSV_HEADERS)

    # Formula injection neutralized with single quote prefix
    assert "'=SUM(A1:A10)" in decoded
    assert "'@EVIL_CP" in decoded


# ---------------------------------------------------------------------------
# API tests for Owner Revenue CSV Export: GET /api/v1/owner/reports/revenue/export
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_api_owner_revenue_export_success() -> None:
    set_actor("station_owner")
    db = AsyncMock()

    mock_inv_res = MagicMock()
    mock_inv_res.all.return_value = []
    mock_unbilled_res = MagicMock()
    mock_unbilled_res.all.return_value = []
    db.execute.side_effect = [mock_inv_res, mock_unbilled_res]

    async def override_db() -> AsyncGenerator[AsyncMock, None]:
        yield db

    app.dependency_overrides[get_db_session] = override_db

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        res = await client.get("/api/v1/owner/reports/revenue/export?period=month")

    assert res.status_code == 200
    assert "text/csv" in res.headers["content-type"]
    assert "attachment; filename=" in res.headers["content-disposition"]
    assert res.content.startswith(UTF8_BOM.encode("utf-8"))


@pytest.mark.asyncio
async def test_api_owner_revenue_export_other_owner_forbidden() -> None:
    set_actor("station_owner")
    other_owner_id = uuid4()
    station_id = uuid4()
    db = AsyncMock()

    # DB returns that station belongs to other_owner_id
    db.scalar.return_value = other_owner_id

    async def override_db() -> AsyncGenerator[AsyncMock, None]:
        yield db

    app.dependency_overrides[get_db_session] = override_db

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        res = await client.get(
            f"/api/v1/owner/reports/revenue/export?period=month&station_id={station_id}"
        )

    assert res.status_code == 403
    assert "Không có quyền truy cập trạm sạc này" in res.json()["detail"]


@pytest.mark.asyncio
async def test_api_owner_revenue_export_unauthorized() -> None:
    # No actor set -> 401
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        res = await client.get("/api/v1/owner/reports/revenue/export?period=month")

    assert res.status_code == 401


# ---------------------------------------------------------------------------
# API tests for Accountant Revenue CSV Export: GET /api/v1/accounting/reports/revenue/export
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_api_accountant_revenue_export_success() -> None:
    set_actor("accountant")
    db = AsyncMock()

    mock_inv_res = MagicMock()
    mock_inv_res.all.return_value = []
    mock_unbilled_res = MagicMock()
    mock_unbilled_res.all.return_value = []
    db.execute.side_effect = [mock_inv_res, mock_unbilled_res]

    async def override_db() -> AsyncGenerator[AsyncMock, None]:
        yield db

    app.dependency_overrides[get_db_session] = override_db

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        res = await client.get("/api/v1/accounting/reports/revenue/export?period=month")

    assert res.status_code == 200
    assert "text/csv" in res.headers["content-type"]
    assert res.content.startswith(UTF8_BOM.encode("utf-8"))


@pytest.mark.asyncio
async def test_api_accountant_revenue_export_forbidden_for_driver() -> None:
    set_actor("driver")
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        res = await client.get("/api/v1/accounting/reports/revenue/export?period=month")

    assert res.status_code == 403


# ---------------------------------------------------------------------------
# API tests for Reconciliation Issues CSV Export: GET /api/v1/accounting/reconciliation-runs/{run_id}/issues/export
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_api_reconciliation_issues_export_404_if_run_missing() -> None:
    set_actor("accountant")
    db = AsyncMock()
    db.scalar.return_value = None  # Run not found

    async def override_db() -> AsyncGenerator[AsyncMock, None]:
        yield db

    app.dependency_overrides[get_db_session] = override_db
    run_id = uuid4()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        res = await client.get(
            f"/api/v1/accounting/reconciliation-runs/{run_id}/issues/export"
        )

    assert res.status_code == 404
    assert "Không tìm thấy" in res.json()["detail"]


@pytest.mark.asyncio
async def test_api_reconciliation_issues_export_success() -> None:
    set_actor("accountant")
    run_id = uuid4()
    inv_id = uuid4()
    db = AsyncMock()

    mock_run = MagicMock()
    mock_run.id = run_id
    mock_run.status = "completed"
    db.scalar.return_value = mock_run

    issue1 = MagicMock()
    issue1.run_id = run_id
    issue1.session_id = 101
    issue1.issue_type = "tariff_version_mismatch"
    issue1.severity = "warning"
    issue1.recomputed_vnd = 45000
    issue1.billed_vnd = 50000
    issue1.debited_vnd = 50000
    issue1.money_difference_vnd = 5000
    issue1.meter_kwh = Decimal("12.500000")
    issue1.billed_kwh = Decimal("12.500000")
    issue1.kwh_difference = Decimal(0)
    issue1.details = "+Công thức sai lệch cước"  # starts with + dangerous prefix

    mock_exec = MagicMock()
    mock_exec.all.return_value = [(issue1, inv_id)]
    db.execute.return_value = mock_exec

    async def override_db() -> AsyncGenerator[AsyncMock, None]:
        yield db

    app.dependency_overrides[get_db_session] = override_db

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        res = await client.get(
            f"/api/v1/accounting/reconciliation-runs/{run_id}/issues/export"
        )

    assert res.status_code == 200
    assert "text/csv" in res.headers["content-type"]
    assert (
        res.headers["content-disposition"]
        == f'attachment; filename="reconciliation_issues_{run_id}.csv"'
    )
    assert res.content.startswith(UTF8_BOM.encode("utf-8"))

    decoded = res.content.decode("utf-8")
    assert "run_id,session_id,invoice_id,issue_code,severity" in decoded
    assert str(run_id) in decoded
    assert str(inv_id) in decoded
    assert "tariff_version_mismatch,warning,45000,50000,50000,5000" in decoded
    # Neutralization of + in details
    assert "'+Công thức sai lệch cước" in decoded
    assert "completed" in decoded


@pytest.mark.asyncio
async def test_api_reconciliation_issues_export_forbidden_for_station_owner() -> None:
    set_actor("station_owner")
    run_id = uuid4()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        res = await client.get(
            f"/api/v1/accounting/reconciliation-runs/{run_id}/issues/export"
        )

    assert res.status_code == 403
