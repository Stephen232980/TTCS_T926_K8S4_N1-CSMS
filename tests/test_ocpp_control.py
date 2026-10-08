import asyncio
import sys
from datetime import UTC, datetime, timedelta
from time import perf_counter
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.entrypoints.http import app
from src.modules.charging.models import ChargingSession
from src.modules.identity.authorization import CurrentActor
from src.modules.identity.dependencies import get_current_actor
from src.modules.ocpp import control, dispatcher, transport
from src.modules.ocpp.connection_registry import ocpp_connections
from src.modules.ocpp.control import execute_command, scan_control_deadlines
from src.modules.ocpp.control_models import ControlRequest, ControlResult
from src.modules.ocpp.frames import Frame, decode_frame, encode_frame
from src.modules.ocpp.transport import handle_message
from src.platform.audit.models import AuditLog
from src.platform.database.session import SessionFactory, engine, get_db_session
from tests.test_charging_sessions import setup, start


@pytest_asyncio.fixture
async def db_session(monkeypatch):
    # Application commits release savepoints; the outer transaction isolates each test,
    # including immutable audit inserts. No deletion privilege is needed for teardown.
    async with engine.connect() as connection:
        transaction = await connection.begin()
        factory = async_sessionmaker(
            bind=connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        for module in (control, dispatcher, transport, sys.modules[__name__]):
            monkeypatch.setattr(module, "SessionFactory", factory)

        async def database():
            async with factory() as session:
                yield session
                await session.commit()

        app.dependency_overrides[get_db_session] = database
        try:
            async with factory() as session:
                yield session
        finally:
            app.dependency_overrides.clear()
            await transaction.rollback()


async def fixture(session):
    station, charger, _connector, _driver, _card, conn, tag = await setup(session)
    charger.code = charger.code.upper()
    conn.charge_point_code = charger.code.lower()
    charger.last_seen_at = datetime.now(UTC)
    charger.status = "online"
    await session.commit()
    await ocpp_connections.replace(conn)
    return station, charger, conn, tag


def reply_with(conn, status="Accepted", kind=3):
    async def answer(raw):
        frame = decode_frame(raw)
        await handle_message(
            conn,
            encode_frame(
                Frame(
                    kind,
                    frame.message_id,
                    {"status": status},
                    error_code="NotSupported",
                )
            ),
        )

    conn.websocket.send_text = AsyncMock(side_effect=answer)


@pytest.mark.parametrize("outcome", ["Accepted", "Rejected", "Invalid"])
async def test_reset_reply_audit_and_idempotency(db_session, outcome):
    station, charger, conn, _ = await fixture(db_session)
    reply_with(conn, outcome)
    uid = uuid4()
    before = perf_counter()
    result = await execute_command(station.owner_id, uid, "Reset", charger.id)
    assert perf_counter() - before < 5
    assert result["status"] == (outcome if outcome != "Invalid" else "ProtocolError")
    assert await execute_command(station.owner_id, uid, "Reset", charger.id) == result
    assert conn.websocket.send_text.await_count == 1
    assert not conn.pending
    async with SessionFactory() as session:
        request = await session.get(ControlRequest, uid)
        assert request.actor_id == station.owner_id
        assert request.payload == {"type": "Soft"}
        assert (await session.get(ControlResult, uid)).status == result["status"]


@pytest.mark.parametrize("scenario", ["offline", "stale", "no_boot", "archived"])
async def test_unavailable_does_not_send(db_session, scenario):
    station, charger, conn, _ = await fixture(db_session)
    if scenario == "offline":
        await ocpp_connections.remove(charger.code.lower(), conn.websocket)
    elif scenario == "stale":
        charger.last_seen_at = datetime.now(UTC) - timedelta(minutes=10)
    elif scenario == "archived":
        charger.archived_at = datetime.now(UTC)
    else:
        conn.boot_accepted = False
    await db_session.commit()
    before = perf_counter()
    result = await execute_command(station.owner_id, uuid4(), "Reset", charger.id)
    assert result["status"] == "Offline"
    assert perf_counter() - before < 1
    conn.websocket.send_text.assert_not_awaited()


@pytest.mark.parametrize("blocked_send", [False, True])
async def test_timeout_covers_send_and_reply_and_late_reply_is_ignored(
    db_session, monkeypatch, blocked_send
):
    station, charger, conn, _ = await fixture(db_session)

    async def hang(raw):
        await asyncio.sleep(10)

    if blocked_send:
        conn.websocket.send_text = AsyncMock(side_effect=hang)
    monkeypatch.setattr(control, "COMMAND_TIMEOUT", 0.05)
    uid = uuid4()
    result = await execute_command(station.owner_id, uid, "Reset", charger.id)
    assert result["status"] == "Timeout"
    assert not conn.pending
    await handle_message(conn, encode_frame(Frame(3, str(uid), {"status": "Accepted"})))
    async with SessionFactory() as session:
        assert (await session.get(ControlResult, uid)).status == "Timeout"


async def test_disconnect_cancels_wait_without_hanging(db_session):
    station, charger, conn, _ = await fixture(db_session)
    task = asyncio.create_task(
        execute_command(station.owner_id, uuid4(), "Reset", charger.id)
    )
    for _ in range(100):
        if conn.pending:
            break
        await asyncio.sleep(0.01)
    await ocpp_connections.remove(charger.code.lower(), conn.websocket)
    assert (await asyncio.wait_for(task, 1))["status"] == "Disconnected"
    assert not conn.pending


@pytest.mark.parametrize("outcome", ["Accepted", "Rejected", "Offline"])
async def test_remote_stop_waits_for_real_stop_and_settles_energy(db_session, outcome):
    station, charger, conn, tag = await fixture(db_session)
    started = await start(db_session, conn, tag)
    transaction_id = started.payload["transactionId"]
    await db_session.commit()
    reply_with(conn, outcome)
    if outcome == "Offline":
        await ocpp_connections.remove(charger.code.lower(), conn.websocket)
    uid = uuid4()
    assert (
        await execute_command(
            station.owner_id, uid, "RemoteStopTransaction", transaction_id
        )
    )["status"] == outcome
    async with SessionFactory() as session:
        assert (await session.get(ChargingSession, transaction_id)).ended_at is None
    if outcome == "Accepted":
        # Remove the response mock before sending a genuine charger-originated CALL.
        conn.websocket.send_text = AsyncMock()
        await handle_message(
            conn,
            encode_frame(
                Frame(
                    2,
                    str(uuid4()),
                    {
                        "transactionId": transaction_id,
                        "meterStop": 3500,
                        "timestamp": datetime.now(UTC).isoformat(),
                        "reason": "Remote",
                    },
                    action="StopTransaction",
                )
            ),
        )
        async with SessionFactory() as session:
            charging = await session.get(ChargingSession, transaction_id)
            assert charging.ended_at is not None
            assert charging.stop_reason == "Remote"
            assert charging.energy_kwh == 2.5


async def test_accepted_stop_deadline_marks_review_once_and_does_not_close(db_session):
    station, _charger, conn, tag = await fixture(db_session)
    transaction_id = (await start(db_session, conn, tag)).payload["transactionId"]
    await db_session.commit()
    reply_with(conn)
    uid = uuid4()
    await execute_command(
        station.owner_id, uid, "RemoteStopTransaction", transaction_id
    )
    async with SessionFactory() as session, session.begin():
        result = await session.get(ControlResult, uid)
        await scan_control_deadlines(
            session, result.received_at + timedelta(seconds=119)
        )
        charging = await session.get(ChargingSession, transaction_id)
        assert "remote_stop_not_confirmed" not in charging.review_reasons
        assert (
            await scan_control_deadlines(
                session, result.received_at + timedelta(seconds=120)
            )
            >= 1
        )
        assert (
            await scan_control_deadlines(
                session, result.received_at + timedelta(seconds=121)
            )
            == 0
        )
        charging = await session.get(ChargingSession, transaction_id)
        assert charging.ended_at is None
        assert charging.review_reasons.count("remote_stop_not_confirmed") == 1
    conn.websocket.send_text = AsyncMock()
    await handle_message(
        conn,
        encode_frame(
            Frame(
                2,
                str(uuid4()),
                {
                    "transactionId": transaction_id,
                    "meterStop": 3500,
                    "timestamp": datetime.now(UTC).isoformat(),
                    "reason": "Remote",
                },
                action="StopTransaction",
            )
        ),
    )
    async with SessionFactory() as session:
        charging = await session.get(ChargingSession, transaction_id)
        assert charging.ended_at is not None
        assert "remote_stop_not_confirmed" not in charging.review_reasons


@pytest.mark.parametrize("table", ["ocpp_control_requests", "ocpp_control_results"])
@pytest.mark.parametrize("operation", ["UPDATE", "DELETE", "TRUNCATE"])
async def test_database_rejects_audit_mutation(db_session, table, operation):
    statement = (
        f"UPDATE {table} SET "
        + ("action = action" if table.endswith("requests") else "status = status")
        if operation == "UPDATE"
        else f"{operation} " + ("FROM " if operation == "DELETE" else "") + table
    )
    if operation == "TRUNCATE":
        statement += " CASCADE"
    with pytest.raises(DBAPIError, match="append-only"):
        async with db_session.begin_nested():
            await db_session.execute(text(statement))


@pytest.mark.parametrize("role", ["station_owner", "driver", "accountant"])
async def test_unauthorized_cannot_send_or_read_audit(role):
    app.dependency_overrides[get_current_actor] = lambda: CurrentActor(
        uuid4(), frozenset({role})
    )
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            assert (
                await client.post(
                    f"/api/v1/ocpp/charge-points/{uuid4()}/reset",
                    json={"request_id": str(uuid4())},
                )
            ).status_code == 403
            assert (
                await client.post(
                    "/api/v1/ocpp/sessions/1/stop", json={"request_id": str(uuid4())}
                )
            ).status_code == 403
            assert (await client.get("/api/v1/ocpp/control-audit")).status_code == 403
    finally:
        app.dependency_overrides.clear()


async def test_admin_audit_filters_and_no_edit_routes(db_session):
    station, charger, conn, _ = await fixture(db_session)
    reply_with(conn)
    uid = uuid4()
    await execute_command(station.owner_id, uid, "Reset", charger.id, "Hard")
    app.dependency_overrides[get_current_actor] = lambda: CurrentActor(
        station.owner_id, frozenset({"admin"})
    )
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get(
                "/api/v1/ocpp/control-audit", params={"charge_point_code": charger.code}
            )
            assert response.status_code == 200
            data = response.json()
            assert data["total"] == 1
            assert data["items"][0]["id"] == str(uid)
            email = data["items"][0]["actor"]
            assert (
                await client.get(
                    "/api/v1/ocpp/control-audit",
                    params={
                        "charge_point_code": charger.code,
                        "actor_email": email,
                        "from_at": datetime.now(UTC).isoformat(),
                    },
                )
            ).json()["total"] == 0
            assert (
                await client.get(
                    "/api/v1/ocpp/control-audit",
                    params={"charge_point_code": charger.code, "actor_email": email},
                )
            ).json()["total"] == 1
            for method in ("patch", "delete", "put"):
                assert (
                    await getattr(client, method)(f"/api/v1/ocpp/commands/{uid}")
                ).status_code == 405
    finally:
        app.dependency_overrides.clear()


async def test_reset_audit_uses_endpoint_permission_and_role_snapshot(db_session):
    station, charger, conn, _ = await fixture(db_session)
    reply_with(conn)
    uid = uuid4()
    app.dependency_overrides[get_current_actor] = lambda: CurrentActor(
        station.owner_id, frozenset({"admin", "operator", "station_owner"})
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        result = await client.post(
            f"/api/v1/ocpp/charge-points/{charger.id}/reset",
            json={"request_id": str(uid)},
        )
        assert result.status_code == 200
        entry = await db_session.get(ControlRequest, uid)
        assert entry.permission == "ops.connector.reset"
        assert entry.actor_roles == ["admin", "operator", "station_owner"]
        audit = await db_session.scalar(
            select(AuditLog).where(AuditLog.data["request_id"].astext == str(uid))
        )
        assert audit.permission == entry.permission
        assert audit.actor_roles == entry.actor_roles
        spoof = await client.post(
            f"/api/v1/ocpp/charge-points/{charger.id}/reset",
            json={"request_id": str(uuid4()), "permission": "admin.accounts.manage"},
        )
        assert spoof.status_code == 422
        app.dependency_overrides[get_current_actor] = lambda: CurrentActor(
            station.owner_id, frozenset({"admin"})
        )
        assert (
            await client.post(
                f"/api/v1/ocpp/charge-points/{charger.id}/reset",
                json={"request_id": str(uuid4())},
            )
        ).status_code == 403
