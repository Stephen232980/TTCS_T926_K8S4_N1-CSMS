"""Unit tests for S-53: accounting reconciliation runs, anomalies, and pure recompute."""

from collections.abc import AsyncGenerator, Generator
from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from src.entrypoints.http import app
from src.modules.accounting.schemas import (
    ReconciliationRunCreateRequest,
)
from src.modules.accounting.service import (
    calculate_input_hash,
    execute_reconciliation_run,
    resolve_reconciliation_bounds,
)
from src.modules.identity.authorization import CurrentActor
from src.modules.identity.dependencies import get_current_actor
from src.platform.database.session import get_db_session


def actor(role: str = "accountant") -> None:
    app.dependency_overrides[get_current_actor] = lambda: CurrentActor(
        uuid4(), frozenset({role})
    )


BASE = "/api/v1/accounting/reconciliation-runs"


@pytest.fixture(autouse=True)
def clean_actor() -> Generator[None, None, None]:
    actor("accountant")
    mock_db = AsyncMock()
    mock_db.scalar.return_value = None
    mock_db.scalars.return_value.all.return_value = []
    mock_db.execute.return_value.all.return_value = []

    async def override_db() -> AsyncGenerator[AsyncMock, None]:
        yield mock_db

    app.dependency_overrides[get_db_session] = override_db
    yield
    app.dependency_overrides.pop(get_current_actor, None)
    app.dependency_overrides.pop(get_db_session, None)


def test_resolve_bounds() -> None:
    start, end = resolve_reconciliation_bounds(date(2026, 10, 1), date(2026, 10, 31))
    assert start < end
    assert start.tzinfo is not None
    assert end.tzinfo is not None


def test_input_hash_deterministic() -> None:
    d1 = date(2026, 10, 1)
    d2 = date(2026, 10, 31)
    sid = uuid4()
    now = datetime(2026, 10, 31, 23, 59, tzinfo=UTC)
    h1 = calculate_input_hash(d1, d2, sid, now, [1, 2, 3])
    h2 = calculate_input_hash(d1, d2, sid, now, [3, 1, 2])
    assert h1 == h2
    assert len(h1) == 64


def test_create_request_validation() -> None:
    with pytest.raises(ValueError, match="Ngày bắt đầu phải trước"):
        ReconciliationRunCreateRequest(
            date_from=date(2026, 10, 31),
            date_to=date(2026, 10, 1),
        )


@pytest.mark.asyncio
async def test_reconciliation_clean_match() -> None:
    db = AsyncMock()
    sess_id = 100
    st_id = uuid4()
    driver_id = uuid4()
    inv_id = uuid4()

    charging = MagicMock()
    charging.id = sess_id
    charging.driver_id = driver_id
    charging.started_at = datetime(2026, 10, 5, 8, 0, tzinfo=UTC)
    charging.ended_at = datetime(2026, 10, 5, 9, 0, tzinfo=UTC)
    charging.meter_start_wh = Decimal(1000)
    charging.meter_stop_wh = Decimal(11000)
    charging.settlement_reason = "debited"

    invoice = MagicMock()
    invoice.id = inv_id
    invoice.driver_id = driver_id
    invoice.total_vnd = 38500

    station = MagicMock()
    station.id = st_id
    station.name = "Trạm Quận 1"

    charger = MagicMock()
    charger.code = "CP-01"

    connector = MagicMock()
    connector.connector_number = 1

    ledger = MagicMock()
    ledger.amount_vnd = -38500
    ledger.reference_type = "charging_session"

    wallet = MagicMock()
    wallet.driver_id = driver_id

    mock_row = (
        charging,
        invoice,
        station,
        charger,
        connector,
        "driver@csms.vn",
        ledger,
        wallet,
    )

    execute_res = MagicMock()
    execute_res.all.return_value = [mock_row]
    db.execute.return_value = execute_res

    line1 = MagicMock()
    line1.invoice_id = inv_id
    line1.line_type = "energy"
    line1.energy_wh = Decimal(10000)
    line1.rate_vnd = 3850
    line1.amount_vnd = 38500

    scalars_res = MagicMock()
    scalars_res.all.return_value = [line1]
    db.scalars.return_value = scalars_res

    req = ReconciliationRunCreateRequest(
        date_from=date(2026, 10, 1),
        date_to=date(2026, 10, 31),
    )

    run = await execute_reconciliation_run(db, req, actor_id=uuid4())
    assert run.total_sessions == 1
    assert run.matched_sessions == 1
    assert run.mismatch_sessions == 0
    assert run.total_billed_vnd == 38500
    assert run.total_recomputed_vnd == 38500
    assert run.total_debited_vnd == 38500
    assert run.money_discrepancy_vnd == 0
    assert run.total_meter_kwh == Decimal(10)
    assert run.total_billed_kwh == Decimal(10)
    assert run.kwh_discrepancy == Decimal(0)


@pytest.mark.asyncio
async def test_reconciliation_detects_all_anomalies() -> None:
    db = AsyncMock()
    driver_id = uuid4()
    st_id = uuid4()

    # 1. Missing invoice
    c1 = MagicMock()
    c1.id = 1
    c1.driver_id = driver_id
    c1.started_at = datetime(2026, 10, 1, 10, 0, tzinfo=UTC)
    c1.ended_at = datetime(2026, 10, 1, 11, 0, tzinfo=UTC)
    c1.connector_released_at = datetime(2026, 10, 1, 11, 5, tzinfo=UTC)
    c1.billing_lifecycle_version = 1
    c1.meter_start_wh = Decimal(0)
    c1.meter_stop_wh = Decimal(5000)
    c1.settlement_reason = None
    r1 = (c1, None, MagicMock(id=st_id), MagicMock(), MagicMock(), None, None, None)

    # 2. Missing ledger debit (invoice > 0 but ledger is None)
    c2 = MagicMock()
    c2.id = 2
    c2.driver_id = driver_id
    c2.started_at = datetime(2026, 10, 2, 10, 0, tzinfo=UTC)
    c2.ended_at = datetime(2026, 10, 2, 11, 0, tzinfo=UTC)
    c2.meter_start_wh = Decimal(0)
    c2.meter_stop_wh = Decimal(5000)
    c2.settlement_reason = None
    inv2 = MagicMock(id=uuid4(), driver_id=driver_id, total_vnd=20000)
    r2 = (c2, inv2, MagicMock(id=st_id), MagicMock(), MagicMock(), None, None, None)

    # 3. Ledger mismatch (amount diff + wrong driver)
    c3 = MagicMock()
    c3.id = 3
    c3.driver_id = driver_id
    c3.started_at = datetime(2026, 10, 3, 10, 0, tzinfo=UTC)
    c3.ended_at = datetime(2026, 10, 3, 11, 0, tzinfo=UTC)
    c3.meter_start_wh = Decimal(0)
    c3.meter_stop_wh = Decimal(5000)
    c3.settlement_reason = "debited"
    inv3 = MagicMock(id=uuid4(), driver_id=driver_id, total_vnd=20000)
    led3 = MagicMock(amount_vnd=-15000, reference_type="charging_session")
    w3 = MagicMock(driver_id=uuid4())  # wrong driver!
    r3 = (c3, inv3, MagicMock(id=st_id), MagicMock(), MagicMock(), None, led3, w3)

    # 4. Pricing mismatch (invoice amount differs by 1 VND from recomputed)
    c4 = MagicMock()
    c4.id = 4
    c4.driver_id = driver_id
    c4.started_at = datetime(2026, 10, 4, 10, 0, tzinfo=UTC)
    c4.ended_at = datetime(2026, 10, 4, 11, 0, tzinfo=UTC)
    c4.meter_start_wh = Decimal(0)
    c4.meter_stop_wh = Decimal(5000)
    c4.settlement_reason = "debited"
    inv4 = MagicMock(
        id=uuid4(), driver_id=driver_id, total_vnd=19251
    )  # 1 VND mismatch!
    led4 = MagicMock(amount_vnd=-19251, reference_type="charging_session")
    w4 = MagicMock(driver_id=driver_id)
    r4 = (c4, inv4, MagicMock(id=st_id), MagicMock(), MagicMock(), None, led4, w4)

    # 5. Meter decreased & meter missing
    c5 = MagicMock()
    c5.id = 5
    c5.driver_id = driver_id
    c5.started_at = datetime(2026, 10, 5, 10, 0, tzinfo=UTC)
    c5.ended_at = datetime(2026, 10, 5, 11, 0, tzinfo=UTC)
    c5.meter_start_wh = Decimal(5000)
    c5.meter_stop_wh = Decimal(4000)  # Decreased!
    c5.settlement_reason = "zero_invoice"
    inv5 = MagicMock(id=uuid4(), driver_id=driver_id, total_vnd=0)
    r5 = (c5, inv5, MagicMock(id=st_id), MagicMock(), MagicMock(), None, None, None)

    c6 = MagicMock()
    c6.id = 6
    c6.driver_id = driver_id
    c6.started_at = datetime(2026, 10, 6, 10, 0, tzinfo=UTC)
    c6.ended_at = datetime(2026, 10, 6, 11, 0, tzinfo=UTC)
    c6.meter_start_wh = None  # Missing!
    c6.meter_stop_wh = Decimal(5000)
    c6.settlement_reason = "zero_invoice"
    inv6 = MagicMock(id=uuid4(), driver_id=driver_id, total_vnd=0)
    r6 = (c6, inv6, MagicMock(id=st_id), MagicMock(), MagicMock(), None, None, None)

    # 6. Valid Zero Invoice & Legacy Exempt (Should NOT create errors)
    c7 = MagicMock()
    c7.id = 7
    c7.driver_id = driver_id
    c7.started_at = datetime(2026, 10, 7, 10, 0, tzinfo=UTC)
    c7.ended_at = datetime(2026, 10, 7, 11, 0, tzinfo=UTC)
    c7.meter_start_wh = Decimal(0)
    c7.meter_stop_wh = Decimal(0)
    c7.settlement_reason = "zero_invoice"
    inv7 = MagicMock(id=uuid4(), driver_id=driver_id, total_vnd=0)
    r7 = (c7, inv7, MagicMock(id=st_id), MagicMock(), MagicMock(), None, None, None)

    c8 = MagicMock()
    c8.id = 8
    c8.driver_id = driver_id
    c8.started_at = datetime(2026, 10, 8, 10, 0, tzinfo=UTC)
    c8.ended_at = datetime(2026, 10, 8, 11, 0, tzinfo=UTC)
    c8.meter_start_wh = Decimal(0)
    c8.meter_stop_wh = Decimal(5000)
    c8.settlement_reason = "legacy_exempt"
    inv8 = MagicMock(id=uuid4(), driver_id=driver_id, total_vnd=19250)
    r8 = (c8, inv8, MagicMock(id=st_id), MagicMock(), MagicMock(), None, None, None)

    exec_res = MagicMock()
    exec_res.all.return_value = [r1, r2, r3, r4, r5, r6, r7, r8]
    db.execute.return_value = exec_res

    # Lines for inv2, inv3 (match total_vnd so no pricing mismatch)
    line2 = MagicMock()
    line2.invoice_id = inv2.id
    line2.line_type = "energy"
    line2.energy_wh = Decimal(5000)
    line2.rate_vnd = 4000
    line2.amount_vnd = 20000

    line3 = MagicMock()
    line3.invoice_id = inv3.id
    line3.line_type = "energy"
    line3.energy_wh = Decimal(5000)
    line3.rate_vnd = 4000
    line3.amount_vnd = 20000

    # Line for inv4 (5000 Wh * 3850 VND/kWh / 1000 = 19250 VND, but invoice was 19251)
    line4 = MagicMock()
    line4.invoice_id = inv4.id
    line4.line_type = "energy"
    line4.energy_wh = Decimal(5000)
    line4.rate_vnd = 3850
    line4.amount_vnd = 19250

    line8 = MagicMock()
    line8.invoice_id = inv8.id
    line8.line_type = "energy"
    line8.energy_wh = Decimal(5000)
    line8.rate_vnd = 3850
    line8.amount_vnd = 19250

    scalar_res = MagicMock()
    scalar_res.all.return_value = [line2, line3, line4, line8]
    db.scalars.return_value = scalar_res

    req = ReconciliationRunCreateRequest(
        date_from=date(2026, 10, 1),
        date_to=date(2026, 10, 31),
    )

    run = await execute_reconciliation_run(db, req, actor_id=uuid4())

    assert run.total_sessions == 8
    assert run.summary_counts["missing_invoice"] == 1
    assert run.summary_counts["missing_ledger"] == 1
    assert run.summary_counts["ledger_mismatch"] == 1
    assert run.summary_counts["pricing_mismatch"] == 1
    assert run.summary_counts["meter_decreased"] == 1
    assert run.summary_counts["meter_missing"] == 1
    assert run.summary_counts["legacy_exempt"] == 1
    assert run.missing_data_sessions == 1
    assert run.money_discrepancy_vnd > 0


@pytest.mark.asyncio
async def test_api_reconciliation_endpoints() -> None:
    actor("accountant")
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        # Invalid date range:
        res = await client.post(
            BASE,
            json={"date_from": "2026-10-31", "date_to": "2026-10-01"},
        )
        assert res.status_code == 422

        # 404 for non-existent run
        random_id = uuid4()
        res = await client.get(f"{BASE}/{random_id}")
        assert res.status_code == 404

        res = await client.get(f"{BASE}/{random_id}/issues")
        assert res.status_code == 404


@pytest.mark.parametrize("forbidden_role", ["driver", "station_owner", "operator"])
@pytest.mark.asyncio
async def test_reconciliation_endpoints_access_denial(forbidden_role: str) -> None:
    actor(forbidden_role)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        res = await client.get(BASE)
        assert res.status_code == 403

        res = await client.post(
            BASE,
            json={"date_from": "2026-10-01", "date_to": "2026-10-31"},
        )
        assert res.status_code == 403


@pytest.mark.asyncio
async def test_reconciliation_unauthenticated_denial() -> None:
    app.dependency_overrides.pop(get_current_actor, None)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        res = await client.get(BASE)
        assert res.status_code == 401
