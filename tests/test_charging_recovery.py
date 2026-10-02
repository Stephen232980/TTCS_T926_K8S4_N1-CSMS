import asyncio
import json
import random
import socket
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import delete, func, select
from websockets.asyncio.client import connect

from src.config import settings
from src.entrypoints.http import app
from src.modules.charging.models import (
    ChargingSession,
    ChargingSessionEvent,
    MeterSample,
    PendingChargingMessage,
)
from src.modules.charging.recovery import flag_abnormal_sessions
from src.modules.charging.router import ManualCloseRequest, close_session
from src.modules.identity.authorization import CurrentActor
from src.modules.identity.dependencies import get_current_actor
from src.modules.identity.models import User
from src.modules.ocpp.dispatcher import dispatch_call
from src.modules.ocpp.frames import Frame, decode_frame
from src.modules.stations.models import ChargePoint, Connector, Station
from src.platform.database.session import SessionFactory, get_db_session
from tests.test_charging_sessions import call, meter_payload, setup, start
from tests.test_ocpp_foundation import charger_fixture, connection


async def reconnect(session, charger, station):
    conn = connection(charger.id, station.id)
    await call(
        session,
        conn,
        "BootNotification",
        {"chargePointVendor": "V", "chargePointModel": "M"},
    )
    return conn


async def stop(session, conn, tid, stamp, meter=3500):
    return await call(
        session,
        conn,
        "StopTransaction",
        {"transactionId": tid, "meterStop": meter, "timestamp": stamp.isoformat()},
    )


@pytest.mark.asyncio
async def test_reconnect_charging_keeps_identity_and_available_never_guesses_end(
    db_session,
):
    station, charger, _, _, _, conn, tag = await setup(db_session)
    tid = (await start(db_session, conn, tag)).payload["transactionId"]
    fresh = await reconnect(db_session, charger, station)
    for status in ("Available", "Charging"):
        await call(
            db_session,
            fresh,
            "StatusNotification",
            {"connectorId": 1, "status": status, "errorCode": "NoError"},
        )
        tx = await db_session.get(ChargingSession, tid)
        assert tx.ended_at is None and tx.energy_kwh is None
        assert ("available_with_open_session" in tx.review_reasons) == (
            status == "Available"
        )
    assert (
        await db_session.scalar(select(func.count()).select_from(ChargingSession)) == 1
    )
    events = (
        await db_session.scalars(
            select(ChargingSessionEvent.action).where(
                ChargingSessionEvent.session_id == tid
            )
        )
    ).all()
    assert events == ["reconnected", "available_with_open_session", "charging_resumed"]


@pytest.mark.asyncio
async def test_buffered_meter_gaps_dedup_closed_session_and_identity(db_session):
    station, charger, _, _, _, conn, tag = await setup(db_session)
    stamp = datetime.now(UTC) - timedelta(minutes=10)
    tid = (await start(db_session, conn, tag, stamp)).payload["transactionId"]
    await call(
        db_session,
        conn,
        "MeterValues",
        meter_payload(tid, stamp + timedelta(seconds=30), 3000),
    )
    fresh = await reconnect(db_session, charger, station)
    payload = meter_payload(tid, stamp + timedelta(seconds=20), 2000)
    payload["meterValue"].append(
        meter_payload(tid, stamp + timedelta(seconds=10), 1500)["meterValue"][0]
    )
    for _ in range(2):
        assert (await call(db_session, fresh, "MeterValues", payload)).kind == 3
    await stop(db_session, fresh, tid, stamp + timedelta(seconds=60))
    await call(
        db_session,
        fresh,
        "MeterValues",
        meter_payload(tid, stamp + timedelta(seconds=40), 3200),
    )
    await call(
        db_session,
        fresh,
        "MeterValues",
        meter_payload(tid, stamp + timedelta(seconds=70), 9999),
    )
    await call(
        db_session,
        fresh,
        "MeterValues",
        meter_payload(tid + 999999, stamp + timedelta(seconds=50), 3300),
    )
    values = (
        await db_session.scalars(
            select(MeterSample)
            .where(MeterSample.session_id == tid)
            .order_by(MeterSample.timestamp)
        )
    ).all()
    assert [v.value for v in values] == [
        Decimal(1500),
        Decimal(2000),
        Decimal(3000),
        Decimal(3200),
    ]
    assert [int((v.timestamp - stamp).total_seconds()) for v in values] == [
        10,
        20,
        30,
        40,
    ]
    tx = await db_session.get(ChargingSession, tid)
    assert tx.energy_kwh == Decimal("2.5") and not tx.review_reasons
    assert (
        await db_session.scalar(
            select(func.count()).select_from(PendingChargingMessage)
        )
        == 1
    )


@pytest.mark.asyncio
async def test_recovery_conflicting_and_regressing_historical_meter_kept_for_review(
    db_session,
):
    station, charger, _, _, _, conn, tag = await setup(db_session)
    stamp = datetime.now(UTC) - timedelta(minutes=5)
    tid = (await start(db_session, conn, tag, stamp)).payload["transactionId"]
    await call(
        db_session,
        conn,
        "MeterValues",
        meter_payload(tid, stamp + timedelta(seconds=30), 2000),
    )
    fresh = await reconnect(db_session, charger, station)
    await call(
        db_session,
        fresh,
        "MeterValues",
        meter_payload(tid, stamp + timedelta(seconds=20), 2500),
    )
    await call(
        db_session,
        fresh,
        "MeterValues",
        meter_payload(tid, stamp + timedelta(seconds=20), 2600),
    )
    tx = await db_session.get(ChargingSession, tid)
    assert {"meter_regression", "conflicting_meter_timestamp"}.issubset(
        tx.review_reasons
    )
    assert await db_session.scalar(select(func.count()).select_from(MeterSample)) == 2


@pytest.mark.asyncio
async def test_abnormal_threshold_boundary_idempotent_and_late_stop(
    db_session, monkeypatch
):
    monkeypatch.setattr(settings, "charging_abnormal_offline_seconds", 30)
    _, charger, _, _, _, conn, tag = await setup(db_session)
    now = datetime.now(UTC)
    tid = (await start(db_session, conn, tag, now - timedelta(hours=8))).payload[
        "transactionId"
    ]
    tx = await db_session.get(ChargingSession, tid)
    tx.received_at = now - timedelta(hours=8)
    charger.last_seen_at = now - timedelta(seconds=149)
    charger.heartbeat_interval_seconds = 60
    await db_session.flush()
    await flag_abnormal_sessions(db_session, now)
    assert tx.abnormal_since is None
    await flag_abnormal_sessions(db_session, now + timedelta(seconds=1))
    await flag_abnormal_sessions(db_session, now + timedelta(seconds=2))
    assert tx.abnormal_since is not None and tx.ended_at is None
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(ChargingSessionEvent)
            .where(ChargingSessionEvent.action == "offline_timeout")
        )
        == 1
    )
    tx.review_reasons = [*tx.review_reasons, "meter_regression"]
    await stop(db_session, conn, tid, now - timedelta(minutes=5))
    assert tx.abnormal_since is None and "offline_timeout" not in tx.review_reasons
    assert tx.energy_kwh == Decimal("2.5") and "meter_regression" in tx.review_reasons


@pytest.mark.asyncio
async def test_recent_contact_or_newly_received_old_start_is_not_abnormal(db_session):
    _, charger, _, _, _, conn, tag = await setup(db_session)
    now = datetime.now(UTC)
    tid = (await start(db_session, conn, tag, now - timedelta(days=2))).payload[
        "transactionId"
    ]
    tx = await db_session.get(ChargingSession, tid)
    charger.last_seen_at = now - timedelta(seconds=10)
    tx.received_at = now - timedelta(days=2)
    await db_session.flush()
    await flag_abnormal_sessions(db_session, now)
    assert tx.abnormal_since is None
    charger.last_seen_at = None
    tx.received_at = now
    await db_session.flush()
    await flag_abnormal_sessions(db_session, now)
    assert tx.abnormal_since is None


@pytest.mark.asyncio
async def test_manual_close_api_permissions_reason_latest_aggregate_and_audit(
    db_session,
):
    station, _, _, _, _, conn, tag = await setup(db_session)
    stamp = datetime.now(UTC) - timedelta(minutes=10)
    tid = (await start(db_session, conn, tag, stamp)).payload["transactionId"]
    tx = await db_session.get(ChargingSession, tid)
    tx.abnormal_since = stamp
    tx.review_reasons = ["offline_timeout"]
    await call(
        db_session,
        conn,
        "MeterValues",
        meter_payload(tid, stamp + timedelta(seconds=30), 3500),
    )
    await call(
        db_session,
        conn,
        "MeterValues",
        meter_payload(tid, stamp + timedelta(seconds=40), 9999, phase="L1"),
    )
    actor = CurrentActor(station.owner_id, frozenset({"operator"}))

    async def database():
        yield db_session

    app.dependency_overrides[get_db_session] = database
    app.dependency_overrides[get_current_actor] = lambda: actor
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            for role in ("driver", "station_owner", "accountant"):
                actor = CurrentActor(station.owner_id, frozenset({role}))
                assert (
                    await client.post(
                        f"/api/v1/charging/sessions/{tid}/close",
                        json={"reason": "Kiểm tra tại trụ"},
                    )
                ).status_code == 403
            actor = CurrentActor(station.owner_id, frozenset({"accountant"}))
            assert (
                await client.get("/api/v1/charging/sessions?state=abnormal")
            ).json()["total"] == 1
            assert (
                await client.get(f"/api/v1/charging/sessions/{tid}/samples")
            ).status_code == 200
            assert (await client.get("/api/v1/charging/cards")).status_code == 403
            actor = CurrentActor(station.owner_id, frozenset({"operator"}))
            for body in (
                {},
                {"reason": "   "},
                {"reason": "x" * 501},
                {"reason": "ok", "energy_kwh": 10},
            ):
                assert (
                    await client.post(
                        f"/api/v1/charging/sessions/{tid}/close", json=body
                    )
                ).status_code == 422
            closed = await client.post(
                f"/api/v1/charging/sessions/{tid}/close",
                json={"reason": "  Đã kiểm tra tại trụ  "},
            )
            assert closed.status_code == 200 and Decimal(
                closed.json()["energy_kwh"]
            ) == Decimal("2.5")
            assert (
                await client.get("/api/v1/charging/sessions?state=abnormal")
            ).json()["total"] == 0
            assert (
                await client.post(
                    f"/api/v1/charging/sessions/{tid}/close", json={"reason": "Lặp"}
                )
            ).status_code == 409
            events = (
                await client.get(f"/api/v1/charging/sessions/{tid}/events")
            ).json()
            assert (
                events[0]["action"] == "manual_closure"
                and events[0]["details"]["reason"] == "Đã kiểm tra tại trụ"
            )
            assert tx.closed_by == actor.user_id and tx.manual_closed_at is not None
            actor = CurrentActor(uuid4(), frozenset({"station_owner"}))
            assert (
                await client.get(f"/api/v1/charging/sessions/{tid}/events")
            ).status_code == 404
        await stop(db_session, conn, tid, stamp + timedelta(minutes=4), 9999)
        assert tx.energy_kwh == Decimal("2.5") and tx.stop_reason == "ManualClosure"
        assert (
            await db_session.scalar(
                select(func.count()).select_from(PendingChargingMessage)
            )
            == 1
        )
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["normal", "missing", "regressed", "future"])
async def test_manual_close_rejects_missing_invalid_or_normal_session(db_session, case):
    from fastapi import HTTPException

    from src.modules.charging.recovery import manual_close

    station, _, _, _, _, conn, tag = await setup(db_session)
    stamp = datetime.now(UTC) - timedelta(minutes=10)
    tid = (await start(db_session, conn, tag, stamp)).payload["transactionId"]
    tx = await db_session.get(ChargingSession, tid)
    if case != "normal":
        tx.abnormal_since = stamp
    if case in ("regressed", "future"):
        await call(
            db_session,
            conn,
            "MeterValues",
            meter_payload(
                tid,
                datetime.now(UTC) + timedelta(hours=1)
                if case == "future"
                else stamp + timedelta(seconds=10),
                500 if case == "regressed" else 2000,
            ),
        )
    with pytest.raises(HTTPException) as error:
        await manual_close(db_session, tx, station.owner_id, "Kiểm tra")
    assert error.value.status_code == 409 and tx.ended_at is None


@pytest.mark.asyncio
async def test_manual_close_and_late_stop_serialize_without_overwrite():
    from fastapi import HTTPException

    stamp = datetime.now(UTC) - timedelta(minutes=10)
    async with SessionFactory() as session, session.begin():
        station, charger = await charger_fixture(session)
        owner_id, station_id, charger_id = station.owner_id, station.id, charger.id
        connector = Connector(charge_point_id=charger_id, connector_number=1)
        session.add(connector)
        await session.flush()
        tx = ChargingSession(
            charge_point_id=charger_id,
            connector_id=connector.id,
            tag_tail="TEST",
            authorization_status="Invalid",
            started_at=stamp,
            meter_start_wh=Decimal(1000),
            abnormal_since=stamp,
            review_reasons=["offline_timeout"],
        )
        session.add(tx)
        await session.flush()
        tid = tx.id
        session.add(
            MeterSample(
                session_id=tid,
                timestamp=stamp + timedelta(seconds=10),
                measurand="Energy.Active.Import.Register",
                phase="",
                location="Outlet",
                value=Decimal(3500),
                unit="Wh",
            )
        )
    try:

        async def close():
            async with SessionFactory() as session, session.begin():
                try:
                    await close_session(
                        tid,
                        ManualCloseRequest(reason="Kiểm tra"),
                        CurrentActor(owner_id, frozenset({"operator"})),
                        session,
                    )
                    return 200
                except HTTPException as error:
                    return error.status_code

        conn = connection(charger_id, station_id)
        conn.boot_accepted = True
        result, _ = await asyncio.gather(
            close(),
            dispatch_call(
                conn,
                Frame(
                    2,
                    str(uuid4()),
                    {
                        "transactionId": tid,
                        "meterStop": 4000,
                        "timestamp": (stamp + timedelta(minutes=5)).isoformat(),
                    },
                    action="StopTransaction",
                ),
            ),
        )
        async with SessionFactory() as session:
            tx = await session.get(ChargingSession, tid)
            assert tx.ended_at is not None and tx.abnormal_since is None
            assert tx.energy_kwh == (Decimal("2.5") if result == 200 else Decimal(3))
            assert result in (200, 409)
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(ChargingSessionEvent)
                    .where(ChargingSessionEvent.session_id == tid)
                )
                == 1
            )
    finally:
        async with SessionFactory() as session, session.begin():
            await session.execute(
                delete(ChargingSession).where(ChargingSession.id == tid)
            )
            await session.execute(
                delete(Connector).where(Connector.charge_point_id == charger_id)
            )
            await session.execute(
                delete(ChargePoint).where(ChargePoint.id == charger_id)
            )
            await session.execute(delete(Station).where(Station.id == station_id))
            await session.execute(delete(User).where(User.id == owner_id))


@pytest.mark.asyncio
async def test_twenty_chargers_random_reconnect_replay_and_buffered_stop():
    ids = []
    stamp = datetime.now(UTC) - timedelta(minutes=10)
    async with SessionFactory() as session, session.begin():
        station, first = await charger_fixture(session)
        owner_id, station_id = station.owner_id, station.id
        for i in range(20):
            charger = (
                first
                if i == 0
                else ChargePoint(station_id=station_id, code=f"recovery-{uuid4()}")
            )
            if i:
                session.add(charger)
            await session.flush()
            connector = Connector(charge_point_id=charger.id, connector_number=1)
            session.add(connector)
            await session.flush()
            ids.append((charger.id, charger.code))
    tids = []
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    server = await asyncio.to_thread(
        subprocess.Popen,
        [
            sys.executable,
            "-c",
            (
                "import asyncio,sys,uvicorn; "
                "server=uvicorn.Server(uvicorn.Config('src.entrypoints.http:app', host='127.0.0.1', port=int(sys.argv[1]), log_level='error')); "
                "asyncio.run(server.serve(), loop_factory=asyncio.SelectorEventLoop)"
            ),
            str(port),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
    )
    try:
        async with httpx.AsyncClient() as client:
            for _ in range(100):
                try:
                    if (
                        await client.get(
                            f"http://127.0.0.1:{port}/health/ready", timeout=1
                        )
                    ).status_code == 200:
                        break
                except httpx.TransportError:
                    pass
                if server.poll() is not None:
                    pytest.fail("Recovery test server exited before startup")
                await asyncio.sleep(0.1)
            else:
                pytest.fail("Recovery test server did not start")

        async def run(index, code):
            rng = random.Random(2100 + index)
            websocket = await connect(
                f"ws://127.0.0.1:{port}/ocpp/{code}", subprotocols=["ocpp1.6"]
            )

            async def send(action, payload, uid=None):
                await websocket.send(
                    json.dumps([2, uid or str(uuid4()), action, payload])
                )
                return decode_frame(
                    await asyncio.wait_for(websocket.recv(), timeout=10)
                )

            await send(
                "BootNotification", {"chargePointVendor": "V", "chargePointModel": "M"}
            )
            start_uid = str(uuid4())
            start_body = {
                "connectorId": 1,
                "idTag": "TEST",
                "meterStart": 1000,
                "timestamp": stamp.isoformat(),
            }
            tid = (await send("StartTransaction", start_body, start_uid)).payload[
                "transactionId"
            ]
            tids.append(tid)
            for round_number in range(1, rng.randint(3, 6)):
                await websocket.close()
                websocket = await connect(
                    f"ws://127.0.0.1:{port}/ocpp/{code}", subprotocols=["ocpp1.6"]
                )
                await send(
                    "BootNotification",
                    {"chargePointVendor": "V", "chargePointModel": "M"},
                )
                assert (await send("StartTransaction", start_body, start_uid)).payload[
                    "transactionId"
                ] == tid
                await send(
                    "StatusNotification",
                    {"connectorId": 1, "status": "Charging", "errorCode": "NoError"},
                )
                blocks = [
                    meter_payload(
                        tid, stamp + timedelta(seconds=k * 10), 1000 + k * 100
                    )["meterValue"][0]
                    for k in range(1, round_number + 1)
                ]
                rng.shuffle(blocks)
                await send(
                    "MeterValues",
                    {"connectorId": 1, "transactionId": tid, "meterValue": blocks},
                )
            await websocket.close()
            websocket = await connect(
                f"ws://127.0.0.1:{port}/ocpp/{code}", subprotocols=["ocpp1.6"]
            )
            await send(
                "BootNotification", {"chargePointVendor": "V", "chargePointModel": "M"}
            )
            body = {
                "transactionId": tid,
                "meterStop": 3500,
                "timestamp": (stamp + timedelta(minutes=5)).isoformat(),
            }
            uid = str(uuid4())
            await send("StopTransaction", body, uid)
            await send("StopTransaction", body, uid)
            await websocket.close()

        await asyncio.gather(*(run(i, code) for i, (_, code) in enumerate(ids)))
        async with SessionFactory() as session:
            transactions = (
                await session.scalars(
                    select(ChargingSession).where(
                        ChargingSession.charge_point_id.in_([i[0] for i in ids])
                    )
                )
            ).all()
            assert len(transactions) == len(set(tids)) == 20
            assert all(
                tx.ended_at is not None and tx.energy_kwh == Decimal("2.5")
                for tx in transactions
            )
    finally:
        server.terminate()
        try:
            await asyncio.to_thread(server.wait, timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()
            await asyncio.to_thread(server.wait, timeout=5)
        async with SessionFactory() as session, session.begin():
            await session.execute(
                delete(ChargingSession).where(
                    ChargingSession.charge_point_id.in_([i[0] for i in ids])
                )
            )
            await session.execute(
                delete(Connector).where(
                    Connector.charge_point_id.in_([i[0] for i in ids])
                )
            )
            await session.execute(
                delete(ChargePoint).where(ChargePoint.id.in_([i[0] for i in ids]))
            )
            await session.execute(delete(Station).where(Station.id == station_id))
            await session.execute(delete(User).where(User.id == owner_id))
