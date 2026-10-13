from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from src.config import settings
from src.entrypoints.http import app
from src.modules.charging.driver_router import current_snapshot
from src.modules.charging.models import ChargingSession
from src.modules.identity.authorization import CurrentActor
from src.modules.identity.dependencies import get_current_actor
from src.modules.ocpp.control import execute_command
from src.modules.ocpp.control_models import ControlRequest
from tests.test_charging_sessions import call, start
from tests.test_driver_charging import db_session as control_database
from tests.test_driver_charging import fixture as driver_fixture

db_session = control_database
fixture = driver_fixture
from tests.test_ocpp_control import reply_with


async def begin(db, resources):
    _, _, _, driver, _, conn, tag = resources
    result = await start(db, conn, tag, datetime.now(UTC) - timedelta(seconds=2))
    await db.commit()
    return result.payload["transactionId"], driver, conn


async def test_driver_stop_accepted_is_not_end_or_unplug(db_session, fixture):
    sid, driver, conn = await begin(db_session, fixture)
    reply_with(conn)
    key = uuid4()
    result = await execute_command(
        driver.id, key, "RemoteStopTransaction", sid, driver_id=driver.id
    )
    assert result["status"] == "Accepted"
    assert (
        await execute_command(
            driver.id, key, "RemoteStopTransaction", sid, driver_id=driver.id
        )
        == result
    )
    assert conn.websocket.send_text.await_count == 1
    row = await db_session.get(ChargingSession, sid)
    await db_session.refresh(row)
    assert row.ended_at is None and row.connector_released_at is None


async def test_driver_cannot_stop_other_session_even_reusing_key(db_session, fixture):
    sid, driver, conn = await begin(db_session, fixture)
    reply_with(conn)
    key = uuid4()
    await execute_command(
        driver.id, key, "RemoteStopTransaction", sid, driver_id=driver.id
    )
    other_id = uuid4()
    for request in [key, uuid4()]:
        with pytest.raises(HTTPException) as e:
            await execute_command(
                other_id, request, "RemoteStopTransaction", sid, driver_id=other_id
            )
        assert e.value.status_code == 403
    assert conn.websocket.send_text.await_count == 1


async def test_demo_feature_is_disabled_by_default(db_session, fixture, monkeypatch):
    sid, driver, _ = await begin(db_session, fixture)
    monkeypatch.setattr(settings, "demo_driver_unplug_enabled", False)
    with pytest.raises(HTTPException) as e:
        await execute_command(
            driver.id, uuid4(), "DataTransfer", sid, driver_id=driver.id
        )
    assert e.value.status_code == 404
    assert (
        await db_session.scalar(select(func.count()).select_from(ControlRequest)) == 0
    )


async def test_demo_rejects_normal_charger(db_session, fixture, monkeypatch):
    sid, driver, _ = await begin(db_session, fixture)
    monkeypatch.setattr(settings, "demo_driver_unplug_enabled", True)
    with pytest.raises(HTTPException) as e:
        await execute_command(
            driver.id, uuid4(), "DataTransfer", sid, driver_id=driver.id
        )
    assert e.value.status_code == 404


async def test_waiting_snapshot_survives_stop_until_device_available(
    db_session, fixture, monkeypatch
):
    monkeypatch.setattr(settings, "billing_available_confirms_unplug", True)
    sid, driver, conn = await begin(db_session, fixture)
    await call(
        db_session,
        conn,
        "StopTransaction",
        {
            "transactionId": sid,
            "meterStop": 1100,
            "timestamp": datetime.now(UTC).isoformat(),
            "reason": "Remote",
        },
    )
    await db_session.commit()
    snapshot = await current_snapshot(db_session, driver.id)
    assert snapshot["session"] is None
    assert snapshot["awaiting_unplug"]["id"] == sid
    await call(
        db_session,
        conn,
        "StatusNotification",
        {
            "connectorId": 1,
            "status": "Available",
            "errorCode": "NoError",
            "timestamp": datetime.now(UTC).isoformat(),
        },
    )
    await db_session.commit()
    assert (await current_snapshot(db_session, driver.id))["awaiting_unplug"] is None


async def test_driver_http_permissions_and_body(db_session, fixture):
    sid, driver, conn = await begin(db_session, fixture)
    reply_with(conn)
    url = f"/api/v1/driver/charging/sessions/{sid}/stop"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        assert (
            await client.post(url, json={"request_id": str(uuid4())})
        ).status_code == 401
        app.dependency_overrides[get_current_actor] = lambda: CurrentActor(
            driver.id, frozenset({"driver"})
        )
        try:
            assert (
                await client.post(
                    url, json={"request_id": str(uuid4()), "driver_id": str(driver.id)}
                )
            ).status_code == 422
            result = await client.post(url, json={"request_id": str(uuid4())})
            assert result.status_code == 200 and result.json()["status"] == "Accepted"
            assert (
                await client.get(
                    "/api/v1/driver/charging/commands/" + result.json()["id"]
                )
            ).status_code == 200
        finally:
            app.dependency_overrides.pop(get_current_actor, None)


async def test_demo_request_is_durable_and_does_not_fake_release(
    db_session, fixture, monkeypatch
):
    from src.modules.ocpp.connection_registry import ocpp_connections
    from src.modules.ocpp.frames import decode_frame

    monkeypatch.setattr(settings, "billing_available_confirms_unplug", True)
    monkeypatch.setattr(settings, "demo_driver_unplug_enabled", True)
    _, charger, _, _, _, conn, _ = fixture
    await ocpp_connections.remove(conn.charge_point_code, conn.websocket)
    charger.code = "DEMO-STG-TD-" + uuid4().hex[:8]
    conn.charge_point_code = charger.code.lower()
    await db_session.commit()
    await ocpp_connections.replace(conn)
    sid, driver, _ = await begin(db_session, fixture)
    reply_with(conn)
    key = uuid4()
    result = await execute_command(
        driver.id, key, "DataTransfer", sid, driver_id=driver.id
    )
    assert result["status"] == "Accepted"
    frame = decode_frame(conn.websocket.send_text.call_args.args[0])
    assert frame.action == "DataTransfer" and frame.payload["messageId"] == "Unplug"
    assert (
        await execute_command(driver.id, key, "DataTransfer", sid, driver_id=driver.id)
        == result
    )
    assert conn.websocket.send_text.await_count == 1
    row = await db_session.get(ChargingSession, sid)
    await db_session.refresh(row)
    assert row.ended_at is None and row.connector_released_at is None


async def test_stopped_session_settles_only_after_device_unplug_once(
    db_session, monkeypatch
):
    from src.modules.billing import closure
    from src.modules.billing.models import Invoice
    from src.modules.ocpp import control
    from src.modules.wallet.models import Wallet, WalletLedger
    from tests.test_s28_occupation_lifecycle import (
        fixture as occupation_fixture,
    )
    from tests.test_s28_occupation_lifecycle import (
        notify,
        stop,
    )
    from tests.test_t80_invoicing import STAMP

    monkeypatch.setattr(closure, "SessionFactory", control.SessionFactory)
    charging, _, driver, conn = await occupation_fixture(db_session)
    await notify(db_session, conn, "Finishing", STAMP + timedelta(minutes=30))
    await stop(
        db_session, conn, charging, STAMP + timedelta(minutes=31), reason="Remote"
    )
    await db_session.commit()
    assert (await closure.chot_phien(charging.id, settle=True)).status == "pending"
    assert await db_session.scalar(select(func.count()).select_from(Invoice)) == 0
    assert await db_session.scalar(select(func.count()).select_from(WalletLedger)) == 0
    await notify(db_session, conn, "Available", STAMP + timedelta(minutes=42))
    await db_session.commit()
    first = await closure.chot_phien(charging.id, settle=True)
    assert first.status == "ready" and first.invoice.total_vnd == 4400
    for _ in range(3):
        assert (
            await closure.chot_phien(charging.id, settle=True)
        ).invoice.id == first.invoice.id
    assert await db_session.scalar(select(func.count()).select_from(WalletLedger)) == 1
    wallet = await db_session.scalar(
        select(Wallet).where(Wallet.driver_id == driver.id)
    )
    await db_session.refresh(wallet)
    assert wallet.balance_vnd == 1000000 - 4400
