from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from src.modules.charging.models import ChargingSession
from src.modules.identity.authorization import CurrentActor
from src.modules.ocpp.connection_registry import ocpp_connections
from src.modules.ocpp.dispatcher import process_call
from src.modules.ocpp.frames import Frame, decode_frame
from src.modules.ocpp.models import OcppMessageReply
from src.modules.ocpp.monitor_router import MonitorQuery, monitoring_snapshot
from tests.test_charging_sessions import call, meter_payload, setup, start
from tests.test_ocpp_foundation import charger_fixture, connection


async def boot(session, conn):
    return await process_call(
        conn,
        Frame(
            2,
            str(uuid4()),
            {"chargePointVendor": "V", "chargePointModel": "M"},
            action="BootNotification",
        ),
        session,
        record_seen=True,
    )


@pytest.mark.parametrize(
    "action", ["Heartbeat", "StartTransaction", "MeterValues", "StopTransaction"]
)
async def test_cached_business_reply_requires_boot_on_new_socket(db_session, action):
    station, charger, _, _, _, conn, tag = await setup(db_session)
    stamp = datetime.now(UTC) - timedelta(minutes=2)
    tid = (await start(db_session, conn, tag, stamp)).payload["transactionId"]
    payloads = {
        "Heartbeat": {},
        "StartTransaction": {
            "connectorId": 1,
            "idTag": tag,
            "meterStart": 1000,
            "timestamp": stamp.isoformat(),
        },
        "MeterValues": meter_payload(tid, stamp + timedelta(seconds=10), 1500),
        "StopTransaction": {
            "transactionId": tid,
            "meterStop": 2000,
            "timestamp": (stamp + timedelta(seconds=20)).isoformat(),
        },
    }
    frame = Frame(2, str(uuid4()), payloads[action], action=action)
    original = await process_call(conn, frame, db_session, record_seen=True)
    before = await db_session.scalar(select(func.count()).select_from(ChargingSession))
    fresh = connection(charger.id, station.id)
    denied = decode_frame(
        await process_call(fresh, frame, db_session, record_seen=True)
    )
    assert denied.error_code == "SecurityError"
    assert (
        await db_session.get(OcppMessageReply, (charger.id, frame.message_id))
    ).response == original
    assert decode_frame(await boot(db_session, fresh)).payload["status"] == "Accepted"
    assert await process_call(fresh, frame, db_session, record_seen=True) == original
    assert (
        await db_session.scalar(select(func.count()).select_from(ChargingSession))
        == before
    )


async def test_preboot_denial_does_not_poison_later_valid_request(db_session):
    station, charger = await charger_fixture(db_session)
    conn = connection(charger.id, station.id)
    frame = Frame(2, "same-after-boot", {}, action="Heartbeat")
    assert (
        decode_frame(await process_call(conn, frame, db_session)).error_code
        == "SecurityError"
    )
    assert (
        await db_session.get(OcppMessageReply, (charger.id, frame.message_id)) is None
    )
    await boot(db_session, conn)
    assert decode_frame(await process_call(conn, frame, db_session)).kind == 3


@pytest.mark.parametrize("previously_accepted", [False, True])
async def test_rejected_boot_is_not_online_even_with_recent_contact(
    db_session, previously_accepted
):
    station, charger = await charger_fixture(db_session)
    conn = connection(charger.id, station.id)
    if previously_accepted:
        await boot(db_session, conn)
    station.status = "blocked"
    await db_session.flush()
    assert decode_frame(await boot(db_session, conn)).payload["status"] == "Rejected"
    snapshot = await monitoring_snapshot(
        db_session,
        CurrentActor(station.owner_id, frozenset({"station_owner"})),
        MonitorQuery(),
    )
    assert charger.last_seen_at is not None
    assert not snapshot.items[0].online


async def test_online_distinguishes_unbooted_socket_and_survives_registry_restart(
    db_session, monkeypatch
):
    station, charger = await charger_fixture(db_session)
    conn = connection(charger.id, station.id)
    actor = CurrentActor(station.owner_id, frozenset({"station_owner"}))
    await boot(db_session, conn)
    snapshot = AsyncMock(return_value={})
    monkeypatch.setattr(ocpp_connections, "snapshot", snapshot)
    assert (
        (await monitoring_snapshot(db_session, actor, MonitorQuery())).items[0].online
    )
    snapshot.return_value = {charger.id: connection(charger.id, station.id)}
    assert (
        not (await monitoring_snapshot(db_session, actor, MonitorQuery()))
        .items[0]
        .online
    )
    snapshot.return_value = {charger.id: conn}
    assert (
        (await monitoring_snapshot(db_session, actor, MonitorQuery())).items[0].online
    )
    snapshot.return_value = {}
    future = charger.last_seen_at + timedelta(
        seconds=2 * charger.heartbeat_interval_seconds + 1
    )
    assert (
        not (await monitoring_snapshot(db_session, actor, MonitorQuery(), future))
        .items[0]
        .online
    )


@pytest.mark.parametrize(
    "value,extra,expected",
    [
        (5000, {}, True),
        (1500, {}, False),
        (5000, {"phase": "L1"}, False),
        (5000, {"location": "Inlet"}, False),
    ],
)
async def test_stop_compares_only_matching_total_energy_series(
    db_session, value, extra, expected
):
    _, _, _, _, _, conn, tag = await setup(db_session)
    stamp = datetime.now(UTC) - timedelta(minutes=2)
    tid = (await start(db_session, conn, tag, stamp)).payload["transactionId"]
    await call(
        db_session,
        conn,
        "MeterValues",
        meter_payload(tid, stamp + timedelta(seconds=10), value, **extra),
    )
    await call(
        db_session,
        conn,
        "StopTransaction",
        {
            "transactionId": tid,
            "meterStop": 2000,
            "timestamp": (stamp + timedelta(seconds=20)).isoformat(),
        },
    )
    tx = await db_session.get(ChargingSession, tid)
    assert ("stop_meter_below_latest" in tx.review_reasons) == expected
    assert tx.energy_kwh == Decimal(1)


async def test_stop_checks_transaction_data_without_using_future_reading(db_session):
    _, _, _, _, _, conn, tag = await setup(db_session)
    stamp = datetime.now(UTC) - timedelta(minutes=2)
    tid = (await start(db_session, conn, tag, stamp)).payload["transactionId"]
    data = meter_payload(tid, stamp + timedelta(seconds=10), 5000)["meterValue"]
    await call(
        db_session,
        conn,
        "StopTransaction",
        {
            "transactionId": tid,
            "meterStop": 2000,
            "timestamp": (stamp + timedelta(seconds=20)).isoformat(),
            "transactionData": data,
        },
    )
    assert (
        "stop_meter_below_latest"
        in (await db_session.get(ChargingSession, tid)).review_reasons
    )
    tid2 = (await start(db_session, conn, tag, stamp)).payload["transactionId"]
    await call(
        db_session,
        conn,
        "MeterValues",
        meter_payload(tid2, stamp + timedelta(seconds=30), 5000),
    )
    await call(
        db_session,
        conn,
        "StopTransaction",
        {
            "transactionId": tid2,
            "meterStop": 2000,
            "timestamp": (stamp + timedelta(seconds=20)).isoformat(),
        },
    )
    assert (
        "stop_meter_below_latest"
        not in (await db_session.get(ChargingSession, tid2)).review_reasons
    )
