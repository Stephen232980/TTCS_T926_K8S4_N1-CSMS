"""Approved S-28 rules exercised through OCPP and persisted PostgreSQL invoices."""

from datetime import timedelta
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import func, select

from src.config import settings
from src.entrypoints.http import app
from src.modules.billing.driver_router import invoice_status
from src.modules.billing.invoicing import lap_hoa_don
from src.modules.billing.models import Invoice
from src.modules.charging.models import ChargingSession, OccupationInterval
from src.modules.identity.authorization import CurrentActor
from src.modules.identity.dependencies import get_current_actor
from src.modules.ocpp.dispatcher import process_call
from src.modules.ocpp.frames import Frame, decode_frame
from src.modules.ocpp.monitoring import expire_chargers
from src.modules.stations.models import ChargePoint
from src.modules.wallet.models import WalletLedger
from tests.test_charging_sessions import setup, start
from tests.test_ocpp_control import db_session as isolated_session
from tests.test_ocpp_foundation import connection
from tests.test_t80_invoicing import STAMP, lines, seed, tariff

db_session = isolated_session


async def fixture(db, *, mode="available", stamp=STAMP, with_tariff=True):
    charging, station, driver, _ = await seed(db, stamp=stamp, with_tariff=with_tariff)
    charging.billing_lifecycle_version = 1
    charging.release_detection = mode
    charging.ended_at = charging.meter_stop_wh = None
    await db.flush()
    conn = connection(charging.charge_point_id)
    conn.boot_accepted = True
    return charging, station, driver, conn


async def call(db, conn, action, payload):
    raw = await process_call(conn, Frame(2, str(uuid4()), payload, action=action), db)
    assert decode_frame(raw).kind == 3


async def notify(db, conn, status, stamp, connector=1):
    payload = {"connectorId": connector, "status": status, "errorCode": "NoError"}
    if stamp is not None:
        payload["timestamp"] = stamp.isoformat()
    await call(db, conn, "StatusNotification", payload)


async def stop(db, conn, charging, stamp, reason="Local", meter=1000):
    await call(
        db,
        conn,
        "StopTransaction",
        {
            "transactionId": charging.id,
            "meterStop": meter,
            "timestamp": stamp.isoformat(),
            "reason": reason,
        },
    )


async def history(db, charging):
    return list(
        await db.scalars(
            select(OccupationInterval)
            .where(OccupationInterval.session_id == charging.id)
            .order_by(OccupationInterval.id)
        )
    )


@pytest.mark.parametrize("order", ["stop_first", "finishing_first", "available_first"])
async def test_approved_example_seven_minutes_until_unplug(db_session, order):
    charging, _, _, conn = await fixture(db_session)
    ledger_before = await db_session.scalar(
        select(func.count()).select_from(WalletLedger)
    )
    idle = STAMP + timedelta(minutes=30)
    end = idle + timedelta(minutes=2)
    finishing = idle + timedelta(minutes=3)
    unplug = idle + timedelta(minutes=12)
    await notify(db_session, conn, "SuspendedEV", idle)
    if order == "stop_first":
        await stop(db_session, conn, charging, end)
    await notify(db_session, conn, "Finishing", finishing)
    if order == "finishing_first":
        await stop(db_session, conn, charging, end)
    pending = await lap_hoa_don(db_session, charging.id)
    assert pending.status == "pending" and pending.invoice is None
    await notify(db_session, conn, "Available", unplug)
    if order == "available_first":
        # Existing recovery policy flags Available while the end meter is absent.
        assert (await lap_hoa_don(db_session, charging.id)).status == "needs_review"
        await stop(db_session, conn, charging, end)
    result = await lap_hoa_don(db_session, charging.id)
    assert result.status == "ready" and result.invoice.total_vnd == 4400
    saved = await lines(db_session, result.invoice)
    energy, occupation = (
        [x for x in saved if x.line_type == "energy"],
        [x for x in saved if x.line_type == "idle"],
    )
    assert sum(x.amount_vnd for x in energy) == 3000
    assert max(x.ended_at for x in energy) == end
    assert [(x.started_at, x.ended_at, x.amount_vnd) for x in occupation] == [
        (idle + timedelta(minutes=5), unplug, 1400)
    ]
    intervals = await history(db_session, charging)
    assert len(intervals) == 1 and intervals[0].confirmed
    assert intervals[0].started_at == idle and intervals[0].ended_at == unplug
    assert (await lap_hoa_don(db_session, charging.id)).invoice.id == result.invoice.id
    assert (
        await db_session.scalar(select(func.count()).select_from(WalletLedger))
        == ledger_before
    )
    assert charging.settlement_completed_at is None


@pytest.mark.parametrize("initial", ["Finishing", "SuspendedEV"])
@pytest.mark.parametrize(
    "seconds,expected", [(299, 0), (300, 0), (301, 200), (360, 200), (361, 400)]
)
async def test_post_stop_interval_grace_and_ceil(
    db_session, initial, seconds, expected
):
    charging, _, _, conn = await fixture(db_session)
    end = STAMP + timedelta(minutes=30)
    await stop(db_session, conn, charging, end)
    await notify(db_session, conn, initial, end + timedelta(minutes=1))
    await notify(
        db_session, conn, "Available", end + timedelta(minutes=1, seconds=seconds)
    )
    result = await lap_hoa_don(db_session, charging.id)
    assert result.status == "ready" and result.invoice.total_vnd == 3000 + expected


@pytest.mark.parametrize("initial", ["SuspendedEV", "Finishing"])
async def test_resume_cancels_candidate_retains_history_and_last_interval_only(
    db_session, initial
):
    charging, _, _, conn = await fixture(db_session)
    await notify(db_session, conn, initial, STAMP + timedelta(minutes=1))
    await notify(db_session, conn, "Charging", STAMP + timedelta(minutes=20))
    await notify(db_session, conn, "SuspendedEV", STAMP + timedelta(minutes=30))
    await stop(db_session, conn, charging, STAMP + timedelta(minutes=32))
    await notify(db_session, conn, "Available", STAMP + timedelta(minutes=42))
    result = await lap_hoa_don(db_session, charging.id)
    assert result.invoice.total_vnd == 4400
    intervals = await history(db_session, charging)
    assert [(x.confirmed, x.end_reason) for x in intervals] == [
        (False, "resumed"),
        (True, "released"),
    ]


async def test_unconfirmed_pause_does_not_make_final_invoice_without_stop(db_session):
    charging, _, _, conn = await fixture(db_session)
    await notify(db_session, conn, "SuspendedEV", STAMP + timedelta(minutes=1))
    await notify(db_session, conn, "Available", STAMP + timedelta(minutes=20))
    assert not (await history(db_session, charging))[0].confirmed
    assert (await lap_hoa_don(db_session, charging.id)).invoice is None


async def test_explicit_disconnect_is_release_evidence(db_session):
    charging, _, _, conn = await fixture(db_session, mode="explicit")
    await notify(db_session, conn, "SuspendedEV", STAMP + timedelta(minutes=30))
    await stop(
        db_session, conn, charging, STAMP + timedelta(minutes=42), "EVDisconnected"
    )
    result = await lap_hoa_don(db_session, charging.id)
    assert result.status == "ready" and result.invoice.total_vnd == 4400


async def test_unverified_available_and_stop_are_not_unplug(db_session):
    charging, _, _, conn = await fixture(db_session, mode="explicit")
    await stop(db_session, conn, charging, STAMP + timedelta(minutes=30))
    await notify(db_session, conn, "Finishing", STAMP + timedelta(minutes=31))
    await notify(db_session, conn, "Available", STAMP + timedelta(minutes=42))
    result = await lap_hoa_don(db_session, charging.id)
    assert result.status == "pending" and result.reason == "invoice_awaiting_unplug"
    assert invoice_status(charging, None) == "awaiting_unplug"


@pytest.mark.parametrize("connector", [0, 99])
async def test_wrong_connector_cannot_release_session(db_session, connector):
    charging, _, _, conn = await fixture(db_session)
    await stop(db_session, conn, charging, STAMP + timedelta(minutes=30))
    await notify(
        db_session, conn, "Available", STAMP + timedelta(minutes=42), connector
    )
    assert (
        await lap_hoa_don(db_session, charging.id)
    ).reason == "invoice_awaiting_unplug"


async def test_stale_and_duplicate_status_do_not_release_or_restart_grace(db_session):
    charging, _, _, conn = await fixture(db_session)
    idle = STAMP + timedelta(minutes=30)
    await notify(db_session, conn, "SuspendedEV", idle)
    await notify(db_session, conn, "Finishing", idle + timedelta(minutes=3))
    for state in ("Available", "Charging", "SuspendedEV"):
        await notify(db_session, conn, state, idle)
    await stop(db_session, conn, charging, idle + timedelta(minutes=2))
    assert charging.connector_released_at is None
    assert charging.review_reasons == []
    await notify(db_session, conn, "Available", idle + timedelta(minutes=12))
    assert (await lap_hoa_don(db_session, charging.id)).invoice.total_vnd == 4400


@pytest.mark.parametrize("state", ["Available", "SuspendedEV", "Finishing", "Charging"])
async def test_missing_timestamp_waits_for_review_without_server_time_billing(
    db_session, state
):
    charging, _, _, conn = await fixture(db_session)
    await notify(db_session, conn, "SuspendedEV", STAMP + timedelta(minutes=30))
    await notify(db_session, conn, state, None)
    await stop(db_session, conn, charging, STAMP + timedelta(minutes=32))
    await notify(db_session, conn, "Available", STAMP + timedelta(minutes=42))
    assert (await lap_hoa_don(db_session, charging.id)).status == "needs_review"
    assert "occupation_missing_status_timestamp" in charging.review_reasons


@pytest.mark.parametrize("state", ["Faulted", "SuspendedEVSE", "Unavailable"])
async def test_interrupted_occupation_requires_review(db_session, state):
    charging, _, _, conn = await fixture(db_session)
    await notify(db_session, conn, "SuspendedEV", STAMP + timedelta(minutes=30))
    await notify(db_session, conn, state, STAMP + timedelta(minutes=31))
    await stop(db_session, conn, charging, STAMP + timedelta(minutes=32))
    await notify(db_session, conn, "Available", STAMP + timedelta(minutes=42))
    assert (await lap_hoa_don(db_session, charging.id)).status == "needs_review"


async def test_offline_after_stop_does_not_bill_unobserved_gap(db_session):
    charging, _, _, conn = await fixture(db_session)
    await stop(db_session, conn, charging, STAMP + timedelta(minutes=30))
    charger = await db_session.get(ChargePoint, charging.charge_point_id)
    charger.last_seen_at = STAMP + timedelta(minutes=31)
    await db_session.flush()
    await expire_chargers(db_session, STAMP + timedelta(hours=1))
    await notify(db_session, conn, "Available", STAMP + timedelta(hours=1))
    assert (await lap_hoa_don(db_session, charging.id)).status == "needs_review"
    assert "occupation_offline_gap" in charging.review_reasons


async def test_idle_after_stop_crosses_midnight_without_extra_energy(db_session):
    stamp = STAMP + timedelta(hours=1, minutes=30)  # 23:00 local.
    charging, station, _, conn = await fixture(db_session, stamp=stamp)
    await tariff(
        db_session, station, station_day := (stamp + timedelta(days=1)).date(), idle=500
    )
    # UTC date is still Oct 10 at 23:00 local; explicitly select Oct 11's tariff.
    assert station_day.day == 11
    await stop(db_session, conn, charging, stamp + timedelta(minutes=30))
    await notify(db_session, conn, "Finishing", stamp + timedelta(minutes=59))
    await notify(
        db_session, conn, "Available", stamp + timedelta(hours=1, minutes=5, seconds=20)
    )
    result = await lap_hoa_don(db_session, charging.id)
    assert result.status == "ready" and result.invoice.total_vnd == 4000
    idle = [x for x in await lines(db_session, result.invoice) if x.line_type == "idle"]
    assert [(x.local_date.day, x.amount_vnd) for x in idle] == [(11, 1000)]


async def test_api_explains_waiting_and_exposes_no_final_amount(db_session):
    charging, _, driver, conn = await fixture(db_session)
    await stop(db_session, conn, charging, STAMP + timedelta(minutes=30))
    app.dependency_overrides[get_current_actor] = lambda: CurrentActor(
        user_id=driver.id, roles=frozenset({"driver"})
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            f"/api/v1/driver/charging/sessions/{charging.id}/invoice"
        )
        listing = await client.get("/api/v1/driver/invoices")
    assert response.json()["status"] == "awaiting_unplug"
    assert response.json()["total_vnd"] is None and response.json()["lines"] == []
    assert listing.json()["items"][0]["status"] == "awaiting_unplug"
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(Invoice)
            .where(Invoice.session_id == charging.id)
        )
        == 0
    )


@pytest.mark.parametrize("available", [False, True])
async def test_start_captures_release_profile_and_setting_is_not_retroactive(
    db_session, monkeypatch, available
):
    _, _, _, _, _, conn, tag = await setup(db_session)
    monkeypatch.setattr(settings, "billing_available_confirms_unplug", available)
    started = await start(db_session, conn, tag, STAMP)
    charging = await db_session.get(ChargingSession, started.payload["transactionId"])
    assert charging.billing_lifecycle_version == 1
    assert charging.release_detection == ("available" if available else "explicit")
    monkeypatch.setattr(settings, "billing_available_confirms_unplug", not available)
    await stop(db_session, conn, charging, STAMP + timedelta(minutes=30), meter=2000)
    await notify(db_session, conn, "Available", STAMP + timedelta(minutes=40))
    assert (charging.connector_released_at is not None) == available


async def test_next_driver_release_cannot_close_previous_driver_invoice(db_session):
    station, _, _, _, _, conn, tag = await setup(db_session)
    await tariff(db_session, station)
    first = await start(db_session, conn, tag, STAMP)
    previous = await db_session.get(ChargingSession, first.payload["transactionId"])
    previous.release_detection = "available"
    await stop(db_session, conn, previous, STAMP + timedelta(minutes=30), meter=2000)
    await notify(db_session, conn, "Finishing", STAMP + timedelta(minutes=31))
    second = await start(db_session, conn, tag, STAMP + timedelta(minutes=45))
    newer = await db_session.get(ChargingSession, second.payload["transactionId"])
    newer.release_detection = "available"
    await db_session.flush()
    await stop(db_session, conn, newer, STAMP + timedelta(minutes=55), meter=2000)
    await notify(db_session, conn, "Available", STAMP + timedelta(minutes=56))
    assert (await lap_hoa_don(db_session, previous.id)).status == "needs_review"
    assert previous.connector_released_at is None
    assert "occupation_replaced_before_release" in previous.review_reasons
    assert (await lap_hoa_don(db_session, newer.id)).status == "ready"


async def test_charging_after_stop_does_not_silently_cancel_occupation(db_session):
    charging, _, _, conn = await fixture(db_session)
    await notify(db_session, conn, "Finishing", STAMP + timedelta(minutes=30))
    await stop(db_session, conn, charging, STAMP + timedelta(minutes=32))
    await notify(db_session, conn, "Charging", STAMP + timedelta(minutes=33))
    await notify(db_session, conn, "Available", STAMP + timedelta(minutes=42))
    assert (await lap_hoa_don(db_session, charging.id)).status == "needs_review"


async def test_no_occupation_energy_only_invoice_still_waits_for_release(db_session):
    charging, _, _, conn = await fixture(db_session)
    await stop(db_session, conn, charging, STAMP + timedelta(minutes=30))
    assert (await lap_hoa_don(db_session, charging.id)).invoice is None
    await notify(db_session, conn, "Available", STAMP + timedelta(minutes=31))
    result = await lap_hoa_don(db_session, charging.id)
    assert result.invoice.total_vnd == 3000
    assert all(x.line_type == "energy" for x in await lines(db_session, result.invoice))
