"""Real committed transactions, ownership and continuing stream authorization."""

import asyncio
import json
import socket
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from time import perf_counter
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
import uvicorn
from fastapi import Request
from sqlalchemy import delete, select, update

from src.entrypoints.http import app
from src.modules.charging import driver_router
from src.modules.charging.models import ChargingSession
from src.modules.identity.models import Role, Session, User, UserRole
from src.modules.identity.security import hash_session_token
from src.modules.stations.models import ChargePoint, Connector, Station
from src.platform.database.session import SessionFactory
from tests.test_charging_sessions import call, meter_payload
from tests.test_ocpp_foundation import charger_fixture, connection


@pytest_asyncio.fixture
async def realtime():
    token, other_token = str(uuid4()), str(uuid4())
    async with SessionFactory() as db, db.begin():
        station, charger = await charger_fixture(db)
        drivers = [
            User(email=f"t48-{uuid4()}@example.com", password_hash="unused")
            for _ in range(2)
        ]
        connectors = [
            Connector(charge_point_id=charger.id, connector_number=i + 1)
            for i in range(2)
        ]
        db.add_all(drivers + connectors)
        role = await db.scalar(select(Role).where(Role.code == "driver"))
        if role is None:
            role = Role(code="driver")
            db.add(role)
        await db.flush()
        db.add_all([UserRole(user_id=d.id, role_id=role.id) for d in drivers])
        db.add_all(
            [
                Session(
                    user_id=d.id,
                    token_hash=hash_session_token(t),
                    expires_at=datetime.now(UTC) + timedelta(hours=1),
                )
                for d, t in zip(drivers, [token, other_token])
            ]
        )
        transactions = [
            ChargingSession(
                charge_point_id=charger.id,
                connector_id=c.id,
                driver_id=d.id,
                tag_tail="TEST",
                authorization_status="Accepted",
                started_at=datetime.now(UTC) - timedelta(seconds=30),
                meter_start_wh=Decimal(1000),
                review_reasons=[],
            )
            for d, c in zip(drivers, connectors)
        ]
        db.add_all(transactions)
        await db.flush()
        data = SimpleNamespace(
            token=token,
            other_token=other_token,
            driver_id=drivers[0].id,
            other_driver_id=drivers[1].id,
            role_id=role.id,
            session_id=transactions[0].id,
            other_session_id=transactions[1].id,
            station_id=station.id,
            owner_id=station.owner_id,
            charger_id=charger.id,
        )
    data.conn = connection(data.charger_id, data.station_id)
    data.conn.boot_accepted = True
    try:
        yield data
    finally:
        async with SessionFactory() as db, db.begin():
            await db.execute(
                delete(ChargingSession).where(
                    ChargingSession.id.in_([data.session_id, data.other_session_id])
                )
            )
            await db.execute(
                delete(Connector).where(Connector.charge_point_id == data.charger_id)
            )
            await db.execute(
                delete(ChargePoint).where(ChargePoint.id == data.charger_id)
            )
            await db.execute(delete(Station).where(Station.id == data.station_id))
            await db.execute(
                delete(User).where(
                    User.id.in_([data.driver_id, data.other_driver_id, data.owner_id])
                )
            )


def request(token):
    result = Request(
        {"type": "http", "headers": [(b"cookie", f"session={token}".encode())]}
    )
    result.is_disconnected = AsyncMock(return_value=False)
    return result


def payload(event):
    return json.loads(event.split("data: ", 1)[1])


async def meter(db, data, value):
    await call(
        db,
        data.conn,
        "MeterValues",
        meter_payload(data.session_id, datetime.now(UTC), value),
    )


@pytest.mark.asyncio
async def test_only_committed_meter_is_emitted_and_reconnect_restores_latest(realtime):
    stream = driver_router.current_events(request(realtime.token), realtime.driver_id)
    first = payload(await anext(stream))
    assert first["session"]["id"] == realtime.session_id
    assert first["session"]["energy_kwh"] == 0
    assert first["start_request"] is None
    try:
        async with SessionFactory() as writer:
            await meter(writer, realtime, 9000)
            # The SSE reader uses another connection and cannot see this flush.
            assert await anext(stream) == ": keepalive\n\n"
            await writer.rollback()
        assert await anext(stream) == ": keepalive\n\n"
        async with SessionFactory() as writer, writer.begin():
            await meter(writer, realtime, 2500)
        began = perf_counter()
        updated = payload(await asyncio.wait_for(anext(stream), 2))
        elapsed = perf_counter() - began
        assert elapsed < 2
        assert updated["session"]["energy_kwh"] == 1.5
        print(f"T-48 committed meter to SSE: {elapsed * 1000:.1f}ms")
    finally:
        await stream.aclose()
    restored = driver_router.current_events(request(realtime.token), realtime.driver_id)
    try:
        assert payload(await anext(restored))["session"]["energy_kwh"] == 1.5
    finally:
        await restored.aclose()


@pytest.mark.asyncio
async def test_other_driver_stream_and_completed_session_are_isolated(realtime):
    stream = driver_router.current_events(
        request(realtime.other_token), realtime.other_driver_id
    )
    own = driver_router.current_events(request(realtime.token), realtime.driver_id)
    try:
        assert (
            payload(await anext(stream))["session"]["id"] == realtime.other_session_id
        )
        await anext(own)
        async with SessionFactory() as writer, writer.begin():
            await meter(writer, realtime, 3500)
        assert await anext(stream) == ": keepalive\n\n"
        assert payload(await anext(own))["session"]["energy_kwh"] == 2.5
        async with SessionFactory() as writer, writer.begin():
            await writer.execute(
                update(ChargingSession)
                .where(ChargingSession.id == realtime.session_id)
                .values(ended_at=datetime.now(UTC), energy_kwh=Decimal("2.5"))
            )
        assert payload(await anext(own))["session"] is None
        assert await anext(stream) == ": keepalive\n\n"
    finally:
        await stream.aclose()
        await own.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("cause", ["logout", "expired", "suspended", "role_removed"])
async def test_stream_stops_after_authorization_changes(realtime, cause):
    stream = driver_router.current_events(request(realtime.token), realtime.driver_id)
    await anext(stream)
    async with SessionFactory() as writer, writer.begin():
        if cause == "role_removed":
            await writer.execute(
                delete(UserRole).where(
                    UserRole.user_id == realtime.driver_id,
                    UserRole.role_id == realtime.role_id,
                )
            )
        elif cause == "suspended":
            await writer.execute(
                update(User)
                .where(User.id == realtime.driver_id)
                .values(status="suspended")
            )
        else:
            values = (
                {"revoked_at": datetime.now(UTC)}
                if cause == "logout"
                else {"expires_at": datetime.now(UTC) - timedelta(seconds=1)}
            )
            await writer.execute(
                update(Session)
                .where(Session.user_id == realtime.driver_id)
                .values(**values)
            )
    assert await anext(stream) == "event: access-denied\ndata: {}\n\n"
    with pytest.raises(StopAsyncIteration):
        await anext(stream)


@pytest.mark.asyncio
async def test_stream_rejects_identity_mismatch(realtime):
    stream = driver_router.current_events(
        request(realtime.other_token), realtime.driver_id
    )
    assert await anext(stream) == "event: access-denied\ndata: {}\n\n"
    with pytest.raises(StopAsyncIteration):
        await anext(stream)


@pytest.mark.asyncio
async def test_sse_http_transport_has_snapshot_and_committed_update_under_two_seconds(
    realtime,
):
    assert set(
        app.openapi()["paths"]["/api/v1/driver/charging/current/events"]["get"][
            "responses"
        ]["200"]["content"]
    ) == {"text/event-stream"}
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", lifespan="off"))
    serving = asyncio.create_task(server.serve(sockets=[listener]))
    try:
        async with asyncio.timeout(10):
            while not server.started:
                if serving.done():
                    await serving
                    raise RuntimeError("SSE test server did not start")
                await asyncio.sleep(0.01)
        async with httpx.AsyncClient(
            base_url=f"http://127.0.0.1:{listener.getsockname()[1]}",
            cookies={"session": realtime.token},
        ) as client:
            async with client.stream(
                "GET",
                f"/api/v1/driver/charging/current/events?session_id={realtime.other_session_id}",
            ) as response:
                assert response.status_code == 200
                assert response.headers["content-type"].startswith("text/event-stream")
                assert response.headers["cache-control"] == "no-store"
                assert response.headers["x-accel-buffering"] == "no"
                lines = response.aiter_lines()

                async def next_snapshot():
                    async for line in lines:
                        if line.startswith("data: "):
                            return json.loads(line[6:])
                    raise AssertionError("Stream ended without a snapshot")

                assert (await asyncio.wait_for(next_snapshot(), 2))["session"][
                    "id"
                ] == realtime.session_id
                async with SessionFactory() as writer, writer.begin():
                    await meter(writer, realtime, 4500)
                began = perf_counter()
                updated = await asyncio.wait_for(next_snapshot(), 2)
                assert updated["session"]["energy_kwh"] == 3.5
                assert perf_counter() - began < 2
                print(f"T-48 real HTTP SSE: {(perf_counter() - began) * 1000:.1f}ms")
            # Existing detail API remains ownership checked, including guessed IDs.
            assert (
                await client.get(
                    f"/api/v1/driver/charging/sessions/{realtime.other_session_id}"
                )
            ).status_code == 403
        async with httpx.AsyncClient(
            base_url=f"http://127.0.0.1:{listener.getsockname()[1]}"
        ) as client:
            assert (
                await client.get("/api/v1/driver/charging/current/events")
            ).status_code == 401
        async with SessionFactory() as writer, writer.begin():
            await writer.execute(
                delete(UserRole).where(UserRole.user_id == realtime.driver_id)
            )
        async with httpx.AsyncClient(
            base_url=f"http://127.0.0.1:{listener.getsockname()[1]}",
            cookies={"session": realtime.token},
        ) as client:
            assert (
                await client.get("/api/v1/driver/charging/current/events")
            ).status_code == 403
    finally:
        server.should_exit = True
        try:
            await asyncio.wait_for(serving, 10)
        finally:
            listener.close()
