import asyncio
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from time import perf_counter
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import delete, func, select

from src.entrypoints.http import app
from src.modules.charging.models import (
    AuthorizationAttempt,
    ChargingCard,
    ChargingSession,
    MeterSample,
    PendingChargingMessage,
)
from src.modules.charging.service import tag_hash
from src.modules.identity.authorization import CurrentActor
from src.modules.identity.dependencies import get_current_actor
from src.modules.identity.models import Role, User, UserRole
from src.modules.ocpp.dispatcher import dispatch_call, process_call
from src.modules.ocpp.frames import Frame, decode_frame
from src.modules.ocpp.transport import handle_message
from src.modules.stations.models import ChargePoint, Connector, Station
from src.platform.database.session import SessionFactory, get_db_session
from tests.test_ocpp_foundation import charger_fixture, connection

TAG = "TEST-DRIVER-ABCD"


@pytest.mark.asyncio
async def test_start_with_another_tag_suffix_does_not_reuse_authorization(db_session):
    _, _, _, _, _, conn, tag = await setup(db_session)
    stamp = datetime.now(UTC)
    first = await start(db_session, conn, tag, stamp)
    second = await start(db_session, conn, "UNKNOWN-" + tag[-4:], stamp)
    assert first.payload["idTagInfo"]["status"] == "Accepted"
    assert second.payload["idTagInfo"]["status"] == "Invalid"
    assert second.payload["transactionId"] != first.payload["transactionId"]


@pytest.mark.asyncio
async def test_start_replay_on_new_connection_keeps_exact_transaction(db_session):
    station, charger, _, _, _, conn, tag = await setup(db_session)
    stamp = datetime.now(UTC)
    message_id = str(uuid4())
    first = await start(db_session, conn, tag, stamp, uid=message_id)
    fresh = connection(charger.id, station.id)
    fresh.boot_accepted = True
    second = await start(db_session, fresh, tag, stamp, uid=message_id)
    assert second.payload == first.payload
    assert (
        await db_session.scalar(select(func.count()).select_from(ChargingSession)) == 1
    )


async def setup(session):
    station, charger = await charger_fixture(session)
    connector = Connector(
        charge_point_id=charger.id, connector_number=1, status="Available"
    )
    driver = User(email=f"driver-{uuid4()}@example.com", password_hash="unused")
    session.add_all([connector, driver])
    role = await session.scalar(select(Role).where(Role.code == "driver"))
    if role is None:
        role = Role(code="driver")
        session.add(role)
    await session.flush()
    session.add(UserRole(user_id=driver.id, role_id=role.id))
    card = ChargingCard(
        tag_hash=tag_hash(TAG + str(charger.id)),
        tag_tail="ABCD",
        driver_id=driver.id,
        issuer_id=station.owner_id,
    )
    # Unique per fixture; protocol and DB use the same exact tag (<=20 characters).
    tag = str(charger.id).replace("-", "")[:16] + "ABCD"
    card.tag_hash = tag_hash(tag)
    session.add(card)
    await session.flush()
    conn = connection(charger.id, station.id)
    conn.boot_accepted = True
    return station, charger, connector, driver, card, conn, tag


async def call(session, conn, action, payload, message_id=None):
    return decode_frame(
        await process_call(
            conn, Frame(2, message_id or str(uuid4()), payload, action=action), session
        )
    )


def meter_payload(transaction_id, stamp, value, **extra):
    return {
        "connectorId": 1,
        "transactionId": transaction_id,
        "meterValue": [
            {
                "timestamp": stamp.isoformat(),
                "sampledValue": [{"value": str(value), **extra}],
            }
        ],
    }


async def start(session, conn, tag, stamp=None, meter=1000, uid=None):
    stamp = stamp or datetime.now(UTC)
    return await call(
        session,
        conn,
        "StartTransaction",
        {
            "connectorId": 1,
            "idTag": tag,
            "meterStart": meter,
            "timestamp": stamp.isoformat(),
        },
        uid,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "scenario, expected",
    [
        ("active", "Accepted"),
        ("locked", "Blocked"),
        ("expired", "Expired"),
        ("unknown", "Invalid"),
        ("suspended_station", "Blocked"),
        ("suspended_driver", "Blocked"),
        ("not_driver", "Blocked"),
    ],
)
async def test_authorize_states_and_masked_audit(
    db_session, caplog, scenario, expected
):
    station, _, _, driver, card, conn, tag = await setup(db_session)
    if scenario == "locked":
        card.status = "blocked"
    if scenario == "expired":
        card.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    if scenario == "suspended_station":
        station.status = "suspended"
    if scenario == "suspended_driver":
        driver.status = "suspended"
    if scenario == "not_driver":
        await db_session.execute(delete(UserRole).where(UserRole.user_id == driver.id))
    if scenario == "unknown":
        tag = "UNKNOWN-CARD-5678"
    await db_session.flush()
    reply = await call(db_session, conn, "Authorize", {"idTag": tag})
    assert reply.payload["idTagInfo"]["status"] == expected
    assert tag not in caplog.text
    attempt = await db_session.scalar(
        select(AuthorizationAttempt).where(
            AuthorizationAttempt.charge_point_id == conn.charge_point_id
        )
    )
    assert attempt.result == expected and attempt.tag_tail == tag[-4:]


@pytest.mark.asyncio
async def test_start_replay_identity_code_lock_and_replacement(db_session, caplog):
    _, charger, _, _, _, conn, tag = await setup(db_session)
    stamp = datetime.now(UTC)
    first = await start(db_session, conn, tag, stamp, uid="start-replay")
    again = await start(db_session, conn, tag, stamp, uid="start-replay")
    assert first.payload == again.payload
    old_id = first.payload["transactionId"]
    assert isinstance(old_id, int)
    await db_session.refresh(charger)
    assert charger.code_locked_at is not None
    second = await start(db_session, conn, tag, stamp + timedelta(seconds=5))
    assert second.payload["transactionId"] > old_id
    old = await db_session.get(ChargingSession, old_id)
    assert old.ended_at is not None and old.stop_reason == "ReplacedByNewTransaction"
    assert old.energy_kwh is None and "replaced_open_session" in old.review_reasons
    assert "ocpp_open_session_replaced" in caplog.text
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(ChargingSession)
            .where(
                ChargingSession.charge_point_id == charger.id,
                ChargingSession.ended_at.is_(None),
            )
        )
        == 1
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind,status", [("blocked", "Blocked"), ("missing", "Invalid")]
)
async def test_invalid_start_still_allocates_review_transaction(
    db_session, kind, status
):
    _, _, _, _, card, conn, tag = await setup(db_session)
    if kind == "blocked":
        card.status = "blocked"
    else:
        tag = "MISSING-TAG"
    await db_session.flush()
    result = await start(db_session, conn, tag)
    assert result.kind == 3 and result.payload["idTagInfo"]["status"] == status
    transaction = await db_session.get(ChargingSession, result.payload["transactionId"])
    assert "authorization_" + status.lower() in transaction.review_reasons


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "meter_stop,energy,review", [(3500, Decimal("2.5"), False), (500, None, True)]
)
async def test_stop_energy_and_transaction_data(db_session, meter_stop, energy, review):
    _, _, _, _, _, conn, tag = await setup(db_session)
    stamp = datetime.now(UTC)
    transaction_id = (await start(db_session, conn, tag, stamp)).payload[
        "transactionId"
    ]
    reply = await call(
        db_session,
        conn,
        "StopTransaction",
        {
            "transactionId": transaction_id,
            "meterStop": meter_stop,
            "timestamp": (stamp + timedelta(seconds=30)).isoformat(),
            "reason": "EVDisconnected",
            "transactionData": meter_payload(
                transaction_id, stamp + timedelta(seconds=20), 2000
            )["meterValue"],
        },
    )
    assert reply.kind == 3
    transaction = await db_session.get(ChargingSession, transaction_id)
    assert transaction.energy_kwh == energy and transaction.ended_at is not None
    assert transaction.stop_reason == "EVDisconnected"
    assert bool(transaction.review_reasons) == review
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(MeterSample)
            .where(MeterSample.session_id == transaction_id)
        )
        == 1
    )


@pytest.mark.asyncio
async def test_unmatched_messages_saved_without_creating_sessions_and_no_raw_tag(
    db_session,
):
    _, charger, _, _, _, conn, tag = await setup(db_session)
    stamp = datetime.now(UTC)
    stop = await call(
        db_session,
        conn,
        "StopTransaction",
        {
            "transactionId": 2147483647,
            "meterStop": 1000,
            "timestamp": stamp.isoformat(),
            "idTag": tag,
        },
    )
    meter = await call(
        db_session, conn, "MeterValues", meter_payload(2147483647, stamp, 1000)
    )
    assert stop.kind == meter.kind == 3
    pending = (
        await db_session.scalars(
            select(PendingChargingMessage).where(
                PendingChargingMessage.charge_point_id == charger.id
            )
        )
    ).all()
    assert len(pending) == 2 and all("idTag" not in item.payload for item in pending)
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(ChargingSession)
            .where(ChargingSession.charge_point_id == charger.id)
        )
        == 0
    )


@pytest.mark.asyncio
async def test_meter_order_duplicate_regression_and_unit_conversion(db_session, caplog):
    _, _, _, _, _, conn, tag = await setup(db_session)
    stamp = datetime.now(UTC)
    transaction_id = (await start(db_session, conn, tag, stamp)).payload[
        "transactionId"
    ]
    await call(
        db_session,
        conn,
        "MeterValues",
        meter_payload(transaction_id, stamp + timedelta(seconds=20), 2, unit="kWh"),
    )
    caplog.clear()
    await call(
        db_session,
        conn,
        "MeterValues",
        meter_payload(transaction_id, stamp + timedelta(seconds=20), 2000),
    )
    assert "ocpp_meter" not in caplog.text
    await call(
        db_session,
        conn,
        "MeterValues",
        meter_payload(transaction_id, stamp + timedelta(seconds=10), 1500),
    )
    assert "old_timestamp" in caplog.text
    await call(
        db_session,
        conn,
        "MeterValues",
        meter_payload(transaction_id, stamp + timedelta(seconds=30), 1900),
    )
    transaction = await db_session.get(ChargingSession, transaction_id)
    assert "meter_regression" in transaction.review_reasons
    rows = (
        await db_session.scalars(
            select(MeterSample)
            .where(MeterSample.session_id == transaction_id)
            .order_by(MeterSample.timestamp)
        )
    ).all()
    assert [row.value for row in rows] == [Decimal(2000), Decimal(1900)]
    assert all(row.unit == "Wh" for row in rows)
    await call(
        db_session,
        conn,
        "StopTransaction",
        {
            "transactionId": transaction_id,
            "meterStop": 4000,
            "timestamp": (stamp + timedelta(seconds=40)).isoformat(),
        },
    )
    assert transaction.energy_kwh == Decimal(
        3
    )  # Difference of endpoints, never sum of samples.


@pytest.mark.asyncio
async def test_known_quantities_unknown_signed_bad_values_and_conflicts(db_session):
    _, _, _, _, _, conn, tag = await setup(db_session)
    stamp = datetime.now(UTC)
    tid = (await start(db_session, conn, tag, stamp)).payload["transactionId"]
    for measurand, value, unit in [
        ("Voltage", "230", "V"),
        ("Power.Active.Import", "7", "kW"),
        ("Unrecognized", "1", "Wh"),
        ("Energy.Active.Import.Register", "NaN", "Wh"),
    ]:
        reply = await call(
            db_session,
            conn,
            "MeterValues",
            meter_payload(
                tid,
                stamp + timedelta(seconds=10),
                value,
                measurand=measurand,
                unit=unit,
            ),
        )
        assert reply.kind == 3
    await call(
        db_session,
        conn,
        "MeterValues",
        meter_payload(
            tid, stamp + timedelta(seconds=15), "signature", format="SignedData"
        ),
    )
    await call(
        db_session,
        conn,
        "MeterValues",
        meter_payload(tid, stamp + timedelta(seconds=20), 2000),
    )
    await call(
        db_session,
        conn,
        "MeterValues",
        meter_payload(tid, stamp + timedelta(seconds=20), 2500),
    )
    transaction = await db_session.get(ChargingSession, tid)
    assert "conflicting_meter_timestamp" in transaction.review_reasons
    values = (
        await db_session.scalars(
            select(MeterSample).where(MeterSample.session_id == tid)
        )
    ).all()
    assert len(values) == 3
    assert (
        next(
            value.value for value in values if value.measurand == "Power.Active.Import"
        )
        == 7000
    )


@pytest.mark.asyncio
async def test_charger_cannot_stop_or_meter_another_chargers_transaction(db_session):
    _, _, _, _, _, first, tag = await setup(db_session)
    _, _, _, _, _, other, _ = await setup(db_session)
    stamp = datetime.now(UTC)
    tid = (await start(db_session, first, tag, stamp)).payload["transactionId"]
    await call(
        db_session,
        other,
        "StopTransaction",
        {
            "transactionId": tid,
            "meterStop": 2000,
            "timestamp": (stamp + timedelta(seconds=10)).isoformat(),
        },
    )
    await call(
        db_session,
        other,
        "MeterValues",
        meter_payload(tid, stamp + timedelta(seconds=10), 2000),
    )
    transaction = await db_session.get(ChargingSession, tid)
    assert transaction.ended_at is None
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(MeterSample)
            .where(MeterSample.session_id == tid)
        )
        == 0
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "action,payload",
    [
        ("Authorize", {"idTag": None}),
        (
            "StartTransaction",
            {
                "connectorId": True,
                "idTag": "TAG",
                "meterStart": 0,
                "timestamp": "2026-10-02T01:00:00Z",
            },
        ),
        ("MeterValues", {"connectorId": 1, "meterValue": []}),
        (
            "StopTransaction",
            {
                "transactionId": 1,
                "meterStop": True,
                "timestamp": "2026-10-02T01:00:00Z",
            },
        ),
        (
            "MeterValues",
            {
                "connectorId": 1,
                "meterValue": [
                    {
                        "timestamp": "2026-10-02T01:00:00Z",
                        "sampledValue": [{"value": "1", "unit": None}],
                    }
                ],
            },
        ),
    ],
)
async def test_invalid_protocol_payload_is_rejected(db_session, action, payload):
    _, _, _, _, _, conn, _ = await setup(db_session)
    assert (await call(db_session, conn, action, payload)).kind == 4


@pytest.mark.asyncio
async def test_api_owner_scope_cards_samples_pending_and_driver_denied(db_session):
    station, _, _, driver, _, conn, tag = await setup(db_session)
    tid = (await start(db_session, conn, tag)).payload["transactionId"]
    actor = CurrentActor(station.owner_id, frozenset({"station_owner"}))

    async def database():
        yield db_session

    app.dependency_overrides[get_db_session] = database
    app.dependency_overrides[get_current_actor] = lambda: actor
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            own = await client.get("/api/v1/charging/sessions")
            assert own.status_code == 200 and own.json()["items"][0]["id"] == tid
            assert tag not in own.text
            assert (
                await client.get(f"/api/v1/charging/sessions/{tid}/samples")
            ).status_code == 200
            duplicate = await client.post(
                "/api/v1/charging/cards",
                json={"id_tag": "ANOTHER-TAG", "driver_email": driver.email},
            )
            assert duplicate.status_code == 201 and "ANOTHER-TAG" not in duplicate.text
            card_id = duplicate.json()["id"]
            assert (
                await client.patch(
                    f"/api/v1/charging/cards/{card_id}", json={"status": "blocked"}
                )
            ).json()["status"] == "blocked"
            actor = CurrentActor(uuid4(), frozenset({"station_owner"}))
            assert (await client.get("/api/v1/charging/sessions")).json()["total"] == 0
            assert (
                await client.get(f"/api/v1/charging/sessions/{tid}/samples")
            ).status_code == 404
            assert (
                await client.patch(
                    f"/api/v1/charging/cards/{card_id}", json={"status": "active"}
                )
            ).status_code == 404
            actor = CurrentActor(driver.id, frozenset({"driver"}))
            for path in ("sessions", "cards", "pending"):
                assert (await client.get("/api/v1/charging/" + path)).status_code == 403
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_committed_replay_and_twenty_concurrent_meter_replies_under_200ms():
    ids = []
    async with SessionFactory() as session, session.begin():
        station, charger = await charger_fixture(session)
        owner_id, station_id = station.owner_id, station.id
        for index in range(20):
            cp = (
                charger
                if index == 0
                else ChargePoint(station_id=station.id, code=f"meter-perf-{uuid4()}")
            )
            if index:
                session.add(cp)
            await session.flush()
            connector = Connector(charge_point_id=cp.id, connector_number=1)
            session.add(connector)
            await session.flush()
            tx = ChargingSession(
                charge_point_id=cp.id,
                connector_id=connector.id,
                driver_id=None,
                tag_tail="TEST",
                authorization_status="Invalid",
                started_at=datetime.now(UTC) - timedelta(seconds=30),
                meter_start_wh=Decimal(1000),
                review_reasons=[],
            )
            session.add(tx)
            await session.flush()
            ids.append((cp.id, tx.id))
    try:
        connections = [connection(cp_id, station_id) for cp_id, _ in ids]
        for conn in connections:
            conn.boot_accepted = True

        async def warm(conn):
            await handle_message(conn, json.dumps([2, str(uuid4()), "Heartbeat", {}]))

        # This NFR concerns periodic reports from already-connected chargers.
        # Establish their DB connections before measuring the 10-second cadence.
        await asyncio.gather(*(warm(conn) for conn in connections))
        frames = [
            Frame(
                2,
                str(uuid4()),
                meter_payload(tid, datetime.now(UTC), 2000),
                action="MeterValues",
            )
            for _, tid in ids
        ]

        async def send(conn, frame):
            raw = json.dumps([2, frame.message_id, frame.action, frame.payload])
            start_time = perf_counter()
            await handle_message(conn, raw)
            elapsed = perf_counter() - start_time
            reply = conn.websocket.send_text.call_args.args[0]
            assert decode_frame(reply).kind == 3
            return elapsed, reply

        results = await asyncio.gather(
            *(send(conn, frame) for conn, frame in zip(connections, frames))
        )
        elapsed = [duration for duration, _ in results]
        print(f"Twenty chargers, full MeterValues replies: max={max(elapsed):.3f}s")
        assert max(elapsed) < 0.2, f"Slowest meter response: {max(elapsed):.3f}s"
        for conn, frame, (_, reply) in zip(connections, frames, results):
            assert await dispatch_call(conn, frame) == reply
        async with SessionFactory() as session:
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(MeterSample)
                    .where(MeterSample.session_id.in_([tid for _, tid in ids]))
                )
                == 20
            )
    finally:
        async with SessionFactory() as session, session.begin():
            await session.execute(
                delete(ChargingSession).where(
                    ChargingSession.id.in_([tid for _, tid in ids])
                )
            )
            await session.execute(
                delete(Connector).where(
                    Connector.charge_point_id.in_([cp for cp, _ in ids])
                )
            )
            await session.execute(
                delete(ChargePoint).where(ChargePoint.id.in_([cp for cp, _ in ids]))
            )
            await session.execute(delete(Station).where(Station.id == station_id))
            await session.execute(delete(User).where(User.id == owner_id))


@pytest.mark.asyncio
async def test_negative_counters_are_retained_for_review(db_session):
    _, _, _, _, _, conn, tag = await setup(db_session)
    stamp = datetime.now(UTC)
    tid = (await start(db_session, conn, tag, stamp, meter=-100)).payload[
        "transactionId"
    ]
    reply = await call(
        db_session,
        conn,
        "StopTransaction",
        {
            "transactionId": tid,
            "meterStop": -10,
            "timestamp": (stamp + timedelta(seconds=10)).isoformat(),
            "transactionData": [{"timestamp": stamp.isoformat(), "sampledValue": []}],
        },
    )
    assert reply.kind == 3
    tx = await db_session.get(ChargingSession, tid)
    assert tx.ended_at is not None and tx.energy_kwh is None
    assert "negative_start_meter" in tx.review_reasons


@pytest.mark.asyncio
async def test_zero_unknown_transaction_is_pending_not_protocol_error(db_session):
    _, _, _, _, _, conn, _ = await setup(db_session)
    reply = await call(
        db_session,
        conn,
        "StopTransaction",
        {
            "transactionId": 0,
            "meterStop": 0,
            "timestamp": datetime.now(UTC).isoformat(),
        },
    )
    assert reply.kind == 3
    assert (
        await db_session.scalar(
            select(func.count()).select_from(PendingChargingMessage)
        )
        == 1
    )
