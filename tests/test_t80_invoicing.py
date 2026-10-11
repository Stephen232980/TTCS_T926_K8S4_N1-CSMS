"""PostgreSQL invoices from persisted charging data, not simulator constants."""

import asyncio
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, localcontext

import httpx
import pytest
from sqlalchemy import event, func, select, text
from sqlalchemy.exc import IntegrityError

from src.entrypoints.http import app
from src.modules.billing.invoicing import InvoiceSessionNotFoundError, lap_hoa_don
from src.modules.billing.models import Invoice, InvoiceLine
from src.modules.charging.models import ChargingSession, MeterSample
from src.modules.identity.authorization import CurrentActor
from src.modules.identity.dependencies import get_current_actor
from src.modules.pricing.models import Tariff, TariffBand
from src.modules.pricing.service import TariffImmutableError, kiem_bieu_gia_co_the_sua
from src.modules.wallet.models import WalletLedger
from src.platform.database.session import SessionFactory
from tests.test_charging_sessions import call, meter_payload, setup, start
from tests.test_ocpp_control import db_session as isolated_session

db_session = isolated_session
STAMP = datetime(2026, 10, 10, 14, 30, tzinfo=UTC)  # 21:30 station time.


async def tariff(db, station, day=date(2026, 10, 10), bands=None, idle=200, grace=5):
    version = Tariff(
        station_id=station.id,
        effective_from=day,
        idle_rate_vnd_per_minute=idle,
        grace_minutes=grace,
    )
    db.add(version)
    await db.flush()
    for start_min, end_min, rate, label in bands or [(0, 1440, 3000, "Cả ngày")]:
        db.add(
            TariffBand(
                tariff_id=version.id,
                start_min=start_min,
                end_min=end_min,
                energy_rate_vnd_per_kwh=rate,
                label=label,
            )
        )
    await db.flush()
    return version


async def seed(
    db,
    *,
    stamp=STAMP,
    duration=timedelta(hours=1),
    first=0,
    last=1000,
    with_tariff=True,
):
    station, charger, connector, driver, *_ = await setup(db)
    charging = ChargingSession(
        charge_point_id=charger.id,
        connector_id=connector.id,
        driver_id=driver.id,
        tag_tail="TEST",
        authorization_status="Accepted",
        started_at=stamp,
        ended_at=stamp + duration,
        meter_start_wh=Decimal(first),
        meter_stop_wh=Decimal(last),
        review_reasons=[],
    )
    db.add(charging)
    await db.flush()
    version = await tariff(db, station) if with_tariff else None
    return charging, station, driver, version


async def lines(db, invoice):
    return list(
        await db.scalars(
            select(InvoiceLine)
            .where(InvoiceLine.invoice_id == invoice.id)
            .order_by(InvoiceLine.started_at, InvoiceLine.line_type)
        )
    )


async def assert_no_invoice(db, charging, reason):
    assert (
        await db.scalar(select(Invoice.id).where(Invoice.session_id == charging.id))
        is None
    )
    assert reason in charging.review_reasons
    again = await lap_hoa_don(db, charging.id)
    assert again.status == "needs_review" and again.invoice is None
    assert charging.review_reasons.count(reason) == 1


async def test_saved_rows_real_rate_rounding_driver_reader_and_no_debit(db_session):
    charging, station, driver, version = await seed(
        db_session, first="500.125", last="1500.625"
    )
    before = await db_session.scalar(select(func.count()).select_from(WalletLedger))
    result = await lap_hoa_don(db_session, charging.id)
    assert result.status == "ready" and result.invoice.total_vnd == 3002
    saved = await lines(db_session, result.invoice)
    assert len(saved) == 1
    assert (saved[0].energy_wh, saved[0].rate_vnd, saved[0].amount_vnd) == (
        Decimal("1000.5"),
        3000,
        3002,
    )
    assert saved[0].tariff_id == version.id and saved[0].band_label == "Cả ngày"
    assert (
        result.invoice.driver_id == driver.id
        and result.invoice.station_id == station.id
    )
    assert version.used_at is not None
    assert (
        charging.settlement_completed_at is None and charging.settlement_reason is None
    )
    assert (
        await db_session.scalar(select(func.count()).select_from(WalletLedger))
        == before
    )
    app.dependency_overrides[get_current_actor] = lambda: CurrentActor(
        user_id=driver.id, roles=frozenset({"driver"})
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            f"/api/v1/driver/charging/sessions/{charging.id}/invoice"
        )
    assert response.status_code == 200
    assert response.json()["total_vnd"] == "3002" and Decimal(
        response.json()["lines"][0]["energy_kwh"]
    ) == Decimal("1.0005")


async def test_kt02_sparse_real_meter_split_has_hand_calculated_lines(db_session):
    charging, station, _, _ = await seed(
        db_session, duration=timedelta(hours=2), last=20000, with_tariff=False
    )
    version = await tariff(
        db_session,
        station,
        bands=[(0, 1320, 3000, "Trước 22h"), (1320, 1440, 2000, "Sau 22h")],
    )
    result = await lap_hoa_don(db_session, charging.id)
    saved = await lines(db_session, result.invoice)
    # 21:30–22:00: 5000 Wh * 3000 / 1000 = 15000; 22:00–23:30: 15000 Wh * 2000 / 1000 = 30000.
    assert [line.energy_wh for line in saved] == [Decimal(5000), Decimal(15000)]
    assert [line.amount_vnd for line in saved] == [15000, 30000]
    assert result.invoice.total_vnd == 45000
    assert all(line.interpolated and line.tariff_id == version.id for line in saved)


async def test_kt03_local_midnight_selects_two_saved_versions(db_session):
    charging, station, _, _ = await seed(
        db_session,
        stamp=STAMP + timedelta(hours=1, minutes=30),
        duration=timedelta(hours=2),
        last=20000,
        with_tariff=False,
    )
    old = await tariff(db_session, station)
    new = await tariff(
        db_session, station, date(2026, 10, 11), [(0, 1440, 4000, "Ngày mới")]
    )
    result = await lap_hoa_don(db_session, charging.id)
    saved = await lines(db_session, result.invoice)
    assert [line.local_date for line in saved] == [
        date(2026, 10, 10),
        date(2026, 10, 11),
    ]
    assert [line.amount_vnd for line in saved] == [30000, 40000]
    assert [line.tariff_id for line in saved] == [old.id, new.id]
    assert result.invoice.total_vnd == 70000


@pytest.mark.parametrize(
    "idle_duration,expected",
    [(None, 0), (timedelta(minutes=5), 0), (timedelta(minutes=35, seconds=20), 6200)],
)
async def test_final_idle_interval_grace_and_ceil_use_t64(
    db_session, idle_duration, expected
):
    charging, _, _, _ = await seed(db_session)
    if idle_duration is not None:
        charging.idle_since = charging.ended_at - idle_duration
    result = await lap_hoa_don(db_session, charging.id)
    saved = await lines(db_session, result.invoice)
    idle = [line for line in saved if line.line_type == "idle"]
    assert sum(line.amount_vnd for line in idle) == expected
    assert result.invoice.total_vnd == 3000 + expected
    assert all(line.energy_wh == 0 and line.rate_vnd == 200 for line in idle)


async def test_idle_cross_midnight_ceil_and_grace_only_once(db_session):
    charging, station, _, _ = await seed(
        db_session,
        stamp=STAMP + timedelta(hours=1, minutes=30),
        duration=timedelta(hours=2),
        with_tariff=False,
    )
    await tariff(db_session, station, idle=200, grace=0)
    await tariff(db_session, station, date(2026, 10, 11), idle=500, grace=90)
    charging.idle_since = datetime(
        2026, 10, 10, 16, 59, 30, tzinfo=UTC
    )  # 23:59:30 -> 01:00:00.
    result = await lap_hoa_don(db_session, charging.id)
    idle = [
        line
        for line in await lines(db_session, result.invoice)
        if line.line_type == "idle"
    ]
    # 61 started minutes: first at 23:59:30 (200), next 60 at new day's rate (500).
    assert [line.amount_vnd for line in idle] == [200, 30000]
    assert sum(line.amount_vnd for line in idle) == 30200


async def test_exact_midnight_stop_does_not_require_next_day_tariff(db_session):
    charging, _, _, _ = await seed(
        db_session, stamp=STAMP + timedelta(hours=1, minutes=30)
    )
    result = await lap_hoa_don(db_session, charging.id)
    assert result.status == "ready" and result.invoice.total_vnd == 3000


async def test_no_tariff_persists_review_reason_and_rolls_back_usage(db_session):
    charging, station, _, _ = await seed(
        db_session,
        stamp=STAMP + timedelta(hours=1, minutes=30),
        duration=timedelta(hours=2),
        with_tariff=False,
    )
    version = await tariff(
        db_session, station, date(2026, 10, 11)
    )  # Missing first day.
    result = await lap_hoa_don(db_session, charging.id)
    assert result.reason == "invoice_missing_tariff"
    await assert_no_invoice(db_session, charging, result.reason)
    assert (await db_session.get(Tariff, version.id)).used_at is None


async def test_existing_review_reason_is_preserved_without_invoice(db_session):
    charging, _, _, version = await seed(db_session)
    charging.review_reasons = ["meter_regression"]
    result = await lap_hoa_don(db_session, charging.id)
    assert result.status == "needs_review" and charging.review_reasons == [
        "meter_regression"
    ]
    assert (
        await db_session.scalar(
            select(Invoice.id).where(Invoice.session_id == charging.id)
        )
        is None
    )
    assert version.used_at is None


@pytest.mark.parametrize(
    "scenario,reason",
    [
        ("negative_start", "invoice_invalid_meter"),
        ("negative_stop", "invoice_invalid_meter"),
        ("missing_stop", "invoice_invalid_meter"),
        ("decreasing", "invoice_meter_decreased"),
        ("intermediate_decrease", "invoice_meter_decreased"),
        ("conflicting_endpoint", "invoice_conflicting_meter"),
        ("wrong_unit", "invoice_invalid_meter"),
        ("zero_duration", "invoice_invalid_interval"),
        ("missing_driver", "invoice_missing_driver"),
        ("invalid_idle", "invoice_invalid_idle_interval"),
        ("unauthorized", "invoice_unauthorized_session"),
    ],
)
async def test_invalid_persisted_data_has_review_reason_and_no_partial_rows(
    db_session, scenario, reason
):
    charging, _, _, version = await seed(db_session)
    tariff_id = version.id
    if scenario == "negative_start":
        charging.meter_start_wh = Decimal(-1)
    if scenario == "negative_stop":
        charging.meter_stop_wh = Decimal(-1)
    if scenario == "missing_stop":
        charging.meter_stop_wh = None
    if scenario == "decreasing":
        charging.meter_start_wh = Decimal(2000)
    if scenario == "zero_duration":
        charging.ended_at = charging.started_at
    if scenario == "missing_driver":
        charging.driver_id = None
    if scenario == "invalid_idle":
        charging.idle_since = charging.started_at - timedelta(seconds=1)
    if scenario == "unauthorized":
        charging.authorization_status = "Blocked"
    if scenario in ("intermediate_decrease", "conflicting_endpoint", "wrong_unit"):
        db_session.add(
            MeterSample(
                session_id=charging.id,
                timestamp=charging.started_at
                if scenario == "conflicting_endpoint"
                else charging.started_at + timedelta(minutes=30),
                measurand="Energy.Active.Import.Register",
                phase="",
                location="Outlet",
                value=Decimal(2000)
                if scenario == "intermediate_decrease"
                else Decimal(50),
                unit="kWh" if scenario == "wrong_unit" else "Wh",
            )
        )
    await db_session.flush()
    result = await lap_hoa_don(db_session, charging.id)
    assert result.reason == reason
    await assert_no_invoice(db_session, charging, reason)
    db_session.expire_all()
    assert (await db_session.get(Tariff, tariff_id)).used_at is None


@pytest.mark.parametrize(
    "bands", [[(0, 600, 3000, "Gap")], [(0, 1000, 3000, "A"), (900, 1440, 4000, "B")]]
)
async def test_invalid_tariff_coverage_never_silently_omits_energy(db_session, bands):
    charging, station, _, _ = await seed(db_session, with_tariff=False)
    version = await tariff(db_session, station, bands=bands)
    key = version.id
    result = await lap_hoa_don(db_session, charging.id)
    assert result.reason == "invoice_invalid_tariff"
    await assert_no_invoice(db_session, charging, result.reason)
    db_session.expire_all()
    assert (await db_session.get(Tariff, key)).used_at is None


async def test_uses_only_total_outlet_register_without_summing_phases(db_session):
    charging, _, _, _ = await seed(db_session)
    for measurand, phase, location, value in [
        ("Power.Active.Import", "", "Outlet", 99999),
        ("Energy.Active.Import.Register", "L1", "Outlet", 99999),
        ("Energy.Active.Import.Register", "", "Inlet", 99999),
    ]:
        db_session.add(
            MeterSample(
                session_id=charging.id,
                timestamp=charging.started_at + timedelta(minutes=30),
                measurand=measurand,
                phase=phase,
                location=location,
                value=value,
                unit="Wh",
            )
        )
    result = await lap_hoa_don(db_session, charging.id)
    assert result.invoice.total_vnd == 3000


async def test_retry_keeps_snapshot_when_new_tariff_is_added(db_session):
    charging, station, _, version = await seed(db_session)
    first = await lap_hoa_don(db_session, charging.id)
    original = [
        (line.id, line.rate_vnd, line.amount_vnd)
        for line in await lines(db_session, first.invoice)
    ]
    await tariff(
        db_session, station, date(2026, 10, 11), [(0, 1440, 99999, "Tương lai")]
    )
    second = await lap_hoa_don(db_session, charging.id)
    assert second.invoice.id == first.invoice.id and second.invoice.total_vnd == 3000
    assert [
        (line.id, line.rate_vnd, line.amount_vnd)
        for line in await lines(db_session, second.invoice)
    ] == original
    with pytest.raises(TariffImmutableError):
        await kiem_bieu_gia_co_the_sua(
            db_session, station_id=station.id, tariff_id=version.id
        )


async def test_open_session_is_pending_without_permanent_review_reason(db_session):
    charging, _, _, _ = await seed(db_session)
    charging.ended_at = None
    result = await lap_hoa_don(db_session, charging.id)
    assert result.status == "pending" and charging.review_reasons == []


async def test_missing_session_is_explicit(db_session):
    with pytest.raises(InvoiceSessionNotFoundError):
        await lap_hoa_don(db_session, -1)


async def test_zero_invoice_is_persisted_without_ledger_or_settlement(db_session):
    charging, _, _, _ = await seed(db_session, last=0)
    result = await lap_hoa_don(db_session, charging.id)
    assert (
        result.invoice.total_vnd == 0 and await lines(db_session, result.invoice) == []
    )
    assert charging.settlement_completed_at is None


async def test_bigint_overflow_rejects_whole_invoice(db_session):
    charging, station, _, _ = await seed(db_session, last=10000, with_tariff=False)
    version = await tariff(db_session, station, bands=[(0, 1440, 2**63 - 1, "Lớn")])
    key = version.id
    result = await lap_hoa_don(db_session, charging.id)
    assert result.reason == "invoice_amount_overflow"
    await assert_no_invoice(db_session, charging, result.reason)
    db_session.expire_all()
    assert (await db_session.get(Tariff, key)).used_at is None


async def test_real_ocpp_wh_kwh_to_saved_invoice(db_session):
    station, _, _, _, _, conn, tag = await setup(db_session)
    await tariff(db_session, station)
    reply = await start(db_session, conn, tag, STAMP, meter=1000)
    session_id = reply.payload["transactionId"]
    await call(
        db_session,
        conn,
        "MeterValues",
        meter_payload(session_id, STAMP + timedelta(minutes=30), "1.5", unit="kWh"),
    )
    await call(
        db_session,
        conn,
        "StopTransaction",
        {
            "transactionId": session_id,
            "meterStop": 2000,
            "timestamp": (STAMP + timedelta(hours=1)).isoformat(),
        },
    )
    result = await lap_hoa_don(db_session, session_id)
    assert result.status == "ready" and result.invoice.total_vnd == 3000


async def test_commit_reload_and_two_workers_wait_for_same_session():
    async with SessionFactory() as db, db.begin():
        charging, _, _, _ = await seed(db)
        session_id = charging.id
    first_done = asyncio.Event()
    release = asyncio.Event()
    worker_pid = asyncio.Future()

    async def first():
        async with SessionFactory() as db, db.begin():
            result = await lap_hoa_don(db, session_id)
            first_done.set()
            await release.wait()
            return result.invoice.id

    async def second():
        async with SessionFactory() as db, db.begin():
            worker_pid.set_result(await db.scalar(text("SELECT pg_backend_pid()")))
            return (await lap_hoa_don(db, session_id)).invoice.id

    winner = asyncio.create_task(first())
    follower = None
    try:
        await asyncio.wait_for(first_done.wait(), 10)
        follower = asyncio.create_task(second())
        pid = await asyncio.wait_for(worker_pid, 10)
        async with SessionFactory() as observer:
            for _ in range(100):
                if await observer.scalar(
                    text("SELECT cardinality(pg_blocking_pids(:pid))"), {"pid": pid}
                ):
                    break
                await asyncio.sleep(0.01)
            else:
                pytest.fail("Second worker did not wait for invoice session lock")
        release.set()
        first_id, second_id = await asyncio.wait_for(
            asyncio.gather(winner, follower), 10
        )
        assert first_id == second_id
    finally:
        release.set()
        await asyncio.gather(
            winner, *([follower] if follower else []), return_exceptions=True
        )
    async with SessionFactory() as db:
        assert (
            await db.scalar(
                select(func.count())
                .select_from(Invoice)
                .where(Invoice.session_id == session_id)
            )
            == 1
        )
        result = await lap_hoa_don(db, session_id)
        assert result.invoice.id == first_id and result.invoice.total_vnd == 3000
        assert len(await lines(db, result.invoice)) == 1


async def test_outer_rollback_undoes_invoice_and_tariff_usage():
    async with SessionFactory() as db, db.begin():
        charging, _, _, version = await seed(db)
        session_id, tariff_id = charging.id, version.id
    async with SessionFactory() as db:
        assert (await lap_hoa_don(db, session_id)).status == "ready"
        await db.rollback()
    async with SessionFactory() as db:
        assert (
            await db.scalar(select(Invoice.id).where(Invoice.session_id == session_id))
            is None
        )
        assert (await db.get(Tariff, tariff_id)).used_at is None


async def test_review_reason_survives_commit_and_status_reader():
    async with SessionFactory() as db, db.begin():
        charging, _, _, _ = await seed(db, with_tariff=False)
        session_id = charging.id
        assert (await lap_hoa_don(db, session_id)).reason == "invoice_missing_tariff"
    async with SessionFactory() as db:
        charging = await db.get(ChargingSession, session_id)
        assert charging.review_reasons == ["invoice_missing_tariff"]
        assert (
            await db.scalar(select(Invoice.id).where(Invoice.session_id == session_id))
            is None
        )


async def test_round_each_segment_before_sum_with_exact_boundary_sample(db_session):
    charging, station, _, _ = await seed(db_session, last=2333, with_tariff=False)
    await tariff(
        db_session, station, bands=[(0, 1320, 3000, "A"), (1320, 1440, 3000, "B")]
    )
    db_session.add(
        MeterSample(
            session_id=charging.id,
            timestamp=STAMP + timedelta(minutes=30),
            measurand="Energy.Active.Import.Register",
            phase="",
            location="Outlet",
            unit="Wh",
            value=Decimal("1166.5"),
        )
    )
    result = await lap_hoa_don(db_session, charging.id)
    assert [line.amount_vnd for line in await lines(db_session, result.invoice)] == [
        3500,
        3500,
    ]
    assert result.invoice.total_vnd == 7000


async def test_other_timezone_selects_station_day_not_utc_day(db_session):
    charging, station, _, _ = await seed(
        db_session, stamp=datetime(2026, 10, 11, 6, 30, tzinfo=UTC), with_tariff=False
    )
    station.timezone = "America/Los_Angeles"
    await tariff(db_session, station)
    await tariff(db_session, station, date(2026, 10, 11), [(0, 1440, 4000, "Mới")])
    result = await lap_hoa_don(db_session, charging.id)
    saved = await lines(db_session, result.invoice)
    assert [line.local_date for line in saved] == [
        date(2026, 10, 10),
        date(2026, 10, 11),
    ]
    assert [line.amount_vnd for line in saved] == [1500, 2000]


async def test_valid_zero_rate_has_energy_snapshot_and_zero_total(db_session):
    charging, station, _, _ = await seed(db_session, with_tariff=False)
    await tariff(db_session, station, bands=[(0, 1440, 0, "")])
    result = await lap_hoa_don(db_session, charging.id)
    saved = await lines(db_session, result.invoice)
    assert result.invoice.total_vnd == 0 and len(saved) == 1
    assert saved[0].energy_wh == 1000 and saved[0].band_label == "00:00–24:00"


async def test_nan_persisted_meter_is_review_not_zero(db_session):
    charging, _, _, _ = await seed(db_session)
    charging.meter_stop_wh = Decimal("NaN")
    result = await lap_hoa_don(db_session, charging.id)
    assert result.reason == "invoice_invalid_meter"
    await assert_no_invoice(db_session, charging, result.reason)


async def test_connector_from_other_station_is_rejected(db_session):
    charging, _, _, _ = await seed(db_session)
    _, _, other, *_ = await setup(db_session)
    charging.connector_id = other.id
    result = await lap_hoa_don(db_session, charging.id)
    assert result.reason == "invoice_session_mismatch"
    await assert_no_invoice(db_session, charging, result.reason)


async def test_small_decimal_context_does_not_change_invoice(db_session):
    charging, _, _, _ = await seed(db_session, first="500.125", last="1500.625")
    with localcontext() as ctx:
        ctx.prec = 3
        result = await lap_hoa_don(db_session, charging.id)
    assert result.invoice.total_vnd == 3002


async def test_large_grace_produces_no_idle_charge_without_datetime_overflow(
    db_session,
):
    charging, _, _, version = await seed(db_session)
    version.grace_minutes = 2**31 - 1
    charging.idle_since = charging.started_at
    result = await lap_hoa_don(db_session, charging.id)
    assert result.status == "ready" and result.invoice.total_vnd == 3000


async def test_line_insert_failure_rolls_back_header_lines_and_usage(db_session):
    charging, _, _, version = await seed(db_session)
    key = version.id

    def invalid_line(_mapper, _connection, target):
        target.amount_vnd = -1

    event.listen(InvoiceLine, "before_insert", invalid_line)
    try:
        with pytest.raises(IntegrityError, match="ck_invoice_lines_nonnegative"):
            await lap_hoa_don(db_session, charging.id)
    finally:
        event.remove(InvoiceLine, "before_insert", invalid_line)
    assert (
        await db_session.scalar(
            select(Invoice.id).where(Invoice.session_id == charging.id)
        )
        is None
    )
    assert (await db_session.get(Tariff, key)).used_at is None
    assert charging.review_reasons == []
    # Caller can retry the whole operation after the technical failure is resolved.
    assert (await lap_hoa_don(db_session, charging.id)).status == "ready"
