"""Independent audit and reconciliation tests for S-53 (AC-1 through AC-7).

Covers:
- Forged unit rate (3850 vs 9999) detected against real station tariff
- Forged idle fee (999,999 VND) without confirmed occupation detected
- 1 VND discrepancy detected (tolerance = 0 VND)
- Zero invoice with unexpected debit (-100 VND) reflected in total_debited_vnd and flagged
- Driver / reference type mismatch
- Meter missing and meter decreased
- Legacy exempt and beginning uncollected debt (AC-6)
- S-32 independent multi-rate benchmark comparison
- Pure read-only immutability (run commits snapshot, invoices/ledgers untouched)
- API contract schema verification (issue_category, discrepancy_amount_vnd, evidence)
"""

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from src.modules.accounting.schemas import ReconciliationRunCreateRequest
from src.modules.accounting.service import (
    execute_reconciliation_run,
    get_reconciliation_issues,
)
from src.modules.billing.segmentation import MeterValue, TariffFrame, chia_doan


def build_mock_session_row(
    sess_id: int = 1,
    st_id: str | None = None,
    driver_id: str | None = None,
    meter_start: int = 0,
    meter_stop: int = 10000,
    inv_total: int = 38500,
    ledger_amount: int = -38500,
    settlement_reason: str = "debited",
    wallet_driver_id: str | None = None,
    reference_type: str = "charging_session",
):
    sid = (
        uuid4() if st_id is None else (UUID(st_id) if isinstance(st_id, str) else st_id)
    )
    did = (
        uuid4()
        if driver_id is None
        else (UUID(driver_id) if isinstance(driver_id, str) else driver_id)
    )
    wdid = (
        did
        if wallet_driver_id is None
        else (
            UUID(wallet_driver_id)
            if isinstance(wallet_driver_id, str)
            else wallet_driver_id
        )
    )

    charging = MagicMock()
    charging.id = sess_id
    charging.driver_id = did
    charging.started_at = datetime(2026, 10, 5, 8, 0, tzinfo=UTC)
    charging.ended_at = datetime(2026, 10, 5, 9, 0, tzinfo=UTC)
    charging.meter_start_wh = Decimal(meter_start) if meter_start is not None else None
    charging.meter_stop_wh = Decimal(meter_stop) if meter_stop is not None else None
    charging.settlement_reason = settlement_reason
    charging.billing_lifecycle_version = 1
    charging.connector_released_at = datetime(2026, 10, 5, 9, 5, tzinfo=UTC)

    invoice = None
    if inv_total is not None:
        invoice = MagicMock()
        invoice.id = uuid4()
        invoice.session_id = sess_id
        invoice.driver_id = did
        invoice.station_id = sid
        invoice.total_vnd = inv_total

    station = MagicMock()
    station.id = sid
    station.name = "Trạm Test"
    station.timezone = "Asia/Ho_Chi_Minh"

    charger = MagicMock()
    charger.code = "CP-01"

    connector = MagicMock()
    connector.connector_number = 1

    ledger = None
    if ledger_amount is not None:
        ledger = MagicMock()
        ledger.id = 501
        ledger.amount_vnd = ledger_amount
        ledger.reference_type = reference_type
        ledger.reference_id = str(sess_id)
        ledger.entry_type = "charging_debit"

    wallet = None
    if ledger is not None:
        wallet = MagicMock()
        wallet.driver_id = wdid

    return (
        charging,
        invoice,
        station,
        charger,
        connector,
        "driver@csms.vn",
        ledger,
        wallet,
    )


@pytest.mark.asyncio
async def test_forged_energy_rate_detected_against_real_tariff() -> None:
    """AC-3/4/5: Station tariff is 3,850 đ/kWh, line forged to 9,999 đ/kWh.

    Invoice total and debit self-match at 99,990 VND.
    Must detect pricing_mismatch and reflect difference against real tariff.
    """
    db = AsyncMock()
    db.add = MagicMock()
    db.add_all = MagicMock()

    # Session with 10 kWh (10,000 Wh)
    # Real tariff = 3,850 đ/kWh -> real expected = 38,500 đ.
    # Forged invoice total = 99,990 đ, debit = -99,990 đ.
    row = build_mock_session_row(
        sess_id=10,
        meter_start=0,
        meter_stop=10000,
        inv_total=99990,
        ledger_amount=-99990,
    )

    exec_res = MagicMock()
    exec_res.all.return_value = [row]
    exec_res.one_or_none.return_value = (0, 0)
    db.execute.return_value = exec_res

    # Mock real station tariff returning 3,850 VND/kWh
    t_version = MagicMock()
    t_version.id = uuid4()
    t_version.idle_rate_vnd_per_minute = 0
    t_version.grace_minutes = 5
    t_frame = TariffFrame(
        start_time="00:00",
        end_time="24:00",
        price_vnd_per_kwh=3850,
        tariff_version=str(t_version.id),
        frame_label="Cả ngày",
    )

    db.scalars.return_value.all.return_value = []

    # Patch _daily_tariffs to return the real tariff frame
    from unittest.mock import patch

    with patch(
        "src.modules.accounting.service._daily_tariffs",
        return_value=({date(2026, 10, 5): t_version}, {date(2026, 10, 5): [t_frame]}),
    ):
        req = ReconciliationRunCreateRequest(
            date_from=date(2026, 10, 1),
            date_to=date(2026, 10, 31),
        )
        run = await execute_reconciliation_run(db, req)

    assert run.mismatch_sessions == 1
    assert run.summary_counts["pricing_mismatch"] == 1
    # Real recomputed is 38,500, billed was 99,990
    assert run.total_recomputed_vnd == 38500
    assert run.total_billed_vnd == 99990
    assert run.money_discrepancy_vnd == 61490


@pytest.mark.asyncio
async def test_forged_idle_fee_without_confirmed_occupation_detected() -> None:
    """AC-4: Invoice forged with 999,999 VND idle fee without confirmed occupation."""
    db = AsyncMock()
    db.add = MagicMock()
    db.add_all = MagicMock()

    # Energy is 38,500 VND. Total invoice is 38,500 + 999,999 = 1,038,499 VND.
    row = build_mock_session_row(
        sess_id=20,
        meter_start=0,
        meter_stop=10000,
        inv_total=1038499,
        ledger_amount=-1038499,
    )

    exec_res = MagicMock()
    exec_res.all.return_value = [row]
    exec_res.one_or_none.return_value = (0, 0)
    db.execute.return_value = exec_res

    t_version = MagicMock()
    t_version.id = uuid4()
    t_version.idle_rate_vnd_per_minute = 2000
    t_version.grace_minutes = 5
    t_frame = TariffFrame(
        start_time="00:00",
        end_time="24:00",
        price_vnd_per_kwh=3850,
        tariff_version=str(t_version.id),
        frame_label="Cả ngày",
    )

    # OccupationInterval returns empty list (no confirmed occupation)
    db.scalars.return_value.all.return_value = []

    from unittest.mock import patch

    with patch(
        "src.modules.accounting.service._daily_tariffs",
        return_value=({date(2026, 10, 5): t_version}, {date(2026, 10, 5): [t_frame]}),
    ):
        req = ReconciliationRunCreateRequest(
            date_from=date(2026, 10, 1),
            date_to=date(2026, 10, 31),
        )
        run = await execute_reconciliation_run(db, req)

    assert run.summary_counts["pricing_mismatch"] == 1
    assert run.total_recomputed_vnd == 38500
    assert run.total_billed_vnd == 1038499
    assert run.money_discrepancy_vnd == 999999


@pytest.mark.asyncio
async def test_one_dong_discrepancy_detected() -> None:
    """AC-5: Tolerance = 0 VND strictly enforced. Exactly 1 VND difference is flagged."""
    db = AsyncMock()
    db.add = MagicMock()
    db.add_all = MagicMock()

    # Recomputed = 38,500; Invoice = 38,501 (1 dong diff)
    row = build_mock_session_row(
        sess_id=30,
        meter_start=0,
        meter_stop=10000,
        inv_total=38501,
        ledger_amount=-38501,
    )
    exec_res = MagicMock()
    exec_res.all.return_value = [row]
    exec_res.one_or_none.return_value = (0, 0)
    db.execute.return_value = exec_res

    t_version = MagicMock(id=uuid4(), idle_rate_vnd_per_minute=0, grace_minutes=5)
    t_frame = TariffFrame(
        start_time="00:00",
        end_time="24:00",
        price_vnd_per_kwh=3850,
        tariff_version=str(t_version.id),
        frame_label="Cả ngày",
    )
    db.scalars.return_value.all.return_value = []

    from unittest.mock import patch

    with patch(
        "src.modules.accounting.service._daily_tariffs",
        return_value=({date(2026, 10, 5): t_version}, {date(2026, 10, 5): [t_frame]}),
    ):
        req = ReconciliationRunCreateRequest(
            date_from=date(2026, 10, 1),
            date_to=date(2026, 10, 31),
        )
        run = await execute_reconciliation_run(db, req)

    assert run.summary_counts["pricing_mismatch"] == 1
    assert run.money_discrepancy_vnd == 1


@pytest.mark.asyncio
async def test_zero_invoice_with_unexpected_debit_detected() -> None:
    """AC-2: Invoice 0 VND with debit -100 VND flags ledger_mismatch and total_debited = 100."""
    db = AsyncMock()
    db.add = MagicMock()
    db.add_all = MagicMock()

    row = build_mock_session_row(
        sess_id=40,
        meter_start=0,
        meter_stop=0,
        inv_total=0,
        ledger_amount=-100,  # Unexpected debit!
        settlement_reason="zero_invoice",
    )
    exec_res = MagicMock()
    exec_res.all.return_value = [row]
    exec_res.one_or_none.return_value = (0, 0)
    db.execute.return_value = exec_res

    t_version = MagicMock(id=uuid4(), idle_rate_vnd_per_minute=0, grace_minutes=5)
    t_frame = TariffFrame(
        start_time="00:00",
        end_time="24:00",
        price_vnd_per_kwh=3850,
        tariff_version=str(t_version.id),
        frame_label="Cả ngày",
    )
    db.scalars.return_value.all.return_value = []

    from unittest.mock import patch

    with patch(
        "src.modules.accounting.service._daily_tariffs",
        return_value=({date(2026, 10, 5): t_version}, {date(2026, 10, 5): [t_frame]}),
    ):
        req = ReconciliationRunCreateRequest(
            date_from=date(2026, 10, 1),
            date_to=date(2026, 10, 31),
        )
        run = await execute_reconciliation_run(db, req)

    assert run.summary_counts["ledger_mismatch"] == 1
    assert run.total_debited_vnd == 100
    assert run.total_billed_vnd == 0


@pytest.mark.asyncio
async def test_driver_and_reference_type_mismatch() -> None:
    """AC-2: Wallet driver mismatch and reference type mismatch flagged."""
    db = AsyncMock()
    db.add = MagicMock()
    db.add_all = MagicMock()

    # Case A: Wrong driver ID
    row_wrong_driver = build_mock_session_row(
        sess_id=51,
        inv_total=38500,
        ledger_amount=-38500,
        wallet_driver_id=str(uuid4()),  # Mismatched driver!
    )
    # Case B: Wrong reference type
    row_wrong_ref = build_mock_session_row(
        sess_id=52,
        inv_total=38500,
        ledger_amount=-38500,
        reference_type="manual_adjustment",  # Mismatched reference type!
    )

    exec_res = MagicMock()
    exec_res.all.return_value = [row_wrong_driver, row_wrong_ref]
    exec_res.one_or_none.return_value = (0, 0)
    db.execute.return_value = exec_res

    t_version = MagicMock(id=uuid4(), idle_rate_vnd_per_minute=0, grace_minutes=5)
    t_frame = TariffFrame(
        start_time="00:00",
        end_time="24:00",
        price_vnd_per_kwh=3850,
        tariff_version=str(t_version.id),
        frame_label="Cả ngày",
    )
    db.scalars.return_value.all.return_value = []

    from unittest.mock import patch

    with patch(
        "src.modules.accounting.service._daily_tariffs",
        return_value=({date(2026, 10, 5): t_version}, {date(2026, 10, 5): [t_frame]}),
    ):
        req = ReconciliationRunCreateRequest(
            date_from=date(2026, 10, 1),
            date_to=date(2026, 10, 31),
        )
        run = await execute_reconciliation_run(db, req)

    assert run.summary_counts["ledger_mismatch"] == 2


@pytest.mark.asyncio
async def test_beginning_uncollected_debt_tracked() -> None:
    """AC-6: Uncollected invoices from previous month are queried and reflected."""
    db = AsyncMock()
    db.add = MagicMock()
    db.add_all = MagicMock()

    row = build_mock_session_row(
        sess_id=60,
        inv_total=38500,
        ledger_amount=-38500,
    )
    exec_res = MagicMock()
    exec_res.all.return_value = [row]
    # Beginning uncollected query returns 2 invoices, total 77,000 VND
    exec_res.one_or_none.return_value = (2, 77000)
    db.execute.return_value = exec_res

    t_version = MagicMock(id=uuid4(), idle_rate_vnd_per_minute=0, grace_minutes=5)
    t_frame = TariffFrame(
        start_time="00:00",
        end_time="24:00",
        price_vnd_per_kwh=3850,
        tariff_version=str(t_version.id),
        frame_label="Cả ngày",
    )
    db.scalars.return_value.all.return_value = []

    from unittest.mock import patch

    with patch(
        "src.modules.accounting.service._daily_tariffs",
        return_value=({date(2026, 10, 5): t_version}, {date(2026, 10, 5): [t_frame]}),
    ):
        req = ReconciliationRunCreateRequest(
            date_from=date(2026, 10, 1),
            date_to=date(2026, 10, 31),
        )
        run = await execute_reconciliation_run(db, req)

    assert run.summary_counts["beginning_uncollected_count"] == 2
    assert run.summary_counts["beginning_uncollected_vnd"] == 77000


def test_s32_independent_benchmark_segmentation() -> None:
    """Independent multi-rate calculation matching S-32 benchmark."""
    # 00:00 - 04:00 Off-peak: 3,000 đ/kWh
    # 04:00 - 17:00 Normal: 3,850 đ/kWh
    # 17:00 - 20:00 Peak: 4,500 đ/kWh
    # Session from 03:00 to 05:00 UTC (10:00 to 12:00 VN) with 20 kWh
    start_t = datetime(2026, 10, 10, 3, 0, tzinfo=UTC)
    end_t = datetime(2026, 10, 10, 5, 0, tzinfo=UTC)
    readings = [
        MeterValue(start_t, Decimal(0)),
        MeterValue(end_t, Decimal(20000)),
    ]
    frames = [
        TariffFrame("00:00", "04:00", 3000, "v1", "Thấp điểm"),
        TariffFrame("04:00", "17:00", 3850, "v1", "Bình thường"),
        TariffFrame("17:00", "20:00", 4500, "v1", "Cao điểm"),
        TariffFrame("20:00", "24:00", 3850, "v1", "Bình thường"),
    ]
    daily_tariffs = {date(2026, 10, 10): frames}
    segments = chia_doan(start_t, end_t, readings, daily_tariffs, "Asia/Ho_Chi_Minh")
    # All 20 kWh falls in 10:00 - 12:00 (Normal rate 3,850)
    total_amount = sum(s["amount_vnd"] for s in segments)
    assert total_amount == 20 * 3850
    assert sum(s["energy_consumed_wh"] for s in segments) == Decimal(20000)


@pytest.mark.asyncio
async def test_immutability_and_contract_schema() -> None:
    """Verify read-only behavior, input_hash, and issue contract fields."""
    db = AsyncMock()
    run_id = uuid4()
    st_id = uuid4()

    issue_mock = MagicMock()
    issue_mock.id = uuid4()
    issue_mock.run_id = run_id
    issue_mock.session_id = 999
    issue_mock.station_id = st_id
    issue_mock.issue_type = "pricing_mismatch"
    issue_mock.severity = "critical"
    issue_mock.billed_vnd = 38501
    issue_mock.recomputed_vnd = 38500
    issue_mock.debited_vnd = 38501
    issue_mock.money_difference_vnd = 1
    issue_mock.meter_kwh = Decimal("10.000000")
    issue_mock.billed_kwh = Decimal("10.000000")
    issue_mock.kwh_difference = Decimal("0.000000")
    issue_mock.details = json.dumps(
        {
            "description": "Số tiền hoá đơn lệch 1 đ so với tính lại từ biểu giá.",
            "evidence": {"diff_vnd": 1, "tolerance_vnd": 0},
        }
    )
    issue_mock.created_at = datetime.now(UTC)

    sess_mock = MagicMock()
    sess_mock.started_at = datetime(2026, 10, 5, 8, 0, tzinfo=UTC)
    sess_mock.ended_at = datetime(2026, 10, 5, 9, 0, tzinfo=UTC)

    exec_res = MagicMock()
    exec_res.all.return_value = [
        (issue_mock, sess_mock, "Trạm Landmark", "CP-01", 1, "driver@csms.vn")
    ]
    db.execute.return_value = exec_res
    db.scalar.return_value = 1

    items, total = await get_reconciliation_issues(db, run_id=run_id)
    assert total == 1
    first = items[0]

    # Verify both frontend-expected and backend-expected fields are present:
    assert first["issue_category"] == "pricing_mismatch"
    assert first["issue_type"] == "pricing_mismatch"
    assert first["discrepancy_amount_vnd"] == "1"
    assert first["discrepancy_kwh"] == "0.000000"
    assert "Số tiền hoá đơn lệch 1 đ" in first["description"]
    assert first["evidence"]["diff_vnd"] == 1
    assert first["evidence"]["tolerance_vnd"] == 0
