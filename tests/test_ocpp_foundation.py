import asyncio
import json
import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import cast
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import WebSocket
from fastapi.testclient import TestClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.entrypoints.http import app
from src.modules.identity.authorization import CurrentActor
from src.modules.identity.dependencies import get_current_actor
from src.modules.identity.models import User
from src.modules.ocpp import router as ocpp_router
from src.modules.ocpp import transport
from src.modules.ocpp.connection_registry import OcppConnection, OcppConnectionRegistry
from src.modules.ocpp.dispatcher import dispatch_call, process_call, prune_replies
from src.modules.ocpp.frames import Frame, FrameError, decode_frame, encode_frame
from src.modules.ocpp.models import OcppMessageReply
from src.modules.ocpp.repository import RegisteredChargePoint
from src.modules.stations.models import ChargePoint, Station
from src.platform.database.session import SessionFactory, get_db_session


@pytest.mark.asyncio
async def test_concurrent_duplicates_are_committed_once_and_replay_in_new_session() -> (
    None
):
    async with SessionFactory() as session, session.begin():
        station, charger = await charger_fixture(session)
        station_id, charger_id, owner_id = station.id, charger.id, station.owner_id
    try:
        frame = Frame(
            2,
            "same-call",
            {"chargePointVendor": "V", "chargePointModel": "M"},
            action="BootNotification",
        )
        first, second = await asyncio.gather(
            dispatch_call(connection(charger_id, station_id), frame),
            dispatch_call(connection(charger_id, station_id), frame),
        )
        assert first == second
        fresh = connection(charger_id, station_id)
        assert await dispatch_call(fresh, frame) == first
        assert fresh.boot_accepted
        async with SessionFactory() as session:
            replies = (
                await session.scalars(
                    select(OcppMessageReply).where(
                        OcppMessageReply.charge_point_id == charger_id
                    )
                )
            ).all()
            assert len(replies) == 1
    finally:
        async with SessionFactory() as session, session.begin():
            await session.execute(
                delete(OcppMessageReply).where(
                    OcppMessageReply.charge_point_id == charger_id
                )
            )
            await session.execute(
                delete(ChargePoint).where(ChargePoint.id == charger_id)
            )
            await session.execute(delete(Station).where(Station.id == station_id))
            await session.execute(delete(User).where(User.id == owner_id))


def connection(charge_point_id=None, station_id=None) -> OcppConnection:
    return OcppConnection(
        charge_point_id or uuid4(),
        station_id or uuid4(),
        "cp-test",
        "active",
        cast(WebSocket, AsyncMock(spec=WebSocket)),
        datetime.now(UTC),
    )


@pytest.mark.parametrize(
    "frame",
    [
        Frame(2, "id", {"value": 1}, action="Test"),
        Frame(3, "id", {}),
        Frame(4, "id", {}, error_code="NotImplemented", description="Not supported"),
    ],
)
def test_frame_round_trip(frame: Frame) -> None:
    assert decode_frame(encode_frame(frame)) == frame


@pytest.mark.parametrize(
    "raw",
    [
        "{}",
        '[2,"id","Action"]',
        '[true,"id",{}]',
        '[2,"id","Action",[]]',
        '[3,"id",{},1]',
        '[4,"id",1,"error",{}]',
        '[2,"id","Action",{"bad":NaN}]',
    ],
)
def test_malformed_frames_are_rejected(raw: str) -> None:
    with pytest.raises(FrameError):
        decode_frame(raw)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", [3, 4])
async def test_server_call_matches_reply_and_cleans_pending(kind: int) -> None:
    conn = connection()
    task = asyncio.create_task(conn.call("Reset", {"type": "Soft"}))
    await asyncio.sleep(0)
    sent = decode_frame(cast(AsyncMock, conn.websocket.send_text).await_args.args[0])
    reply = Frame(
        cast(int, kind),
        sent.message_id,
        {"status": "Accepted"},
        error_code="NotImplemented" if kind == 4 else "",
    )
    await transport.handle_message(conn, encode_frame(reply))
    assert await task == reply
    assert conn.pending == {}


@pytest.mark.asyncio
async def test_duplicate_pending_message_id_is_rejected_before_socket_send(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = connection()
    monkeypatch.setattr(transport, "record_contact", AsyncMock())
    first_call = asyncio.create_task(
        conn.call("Reset", {"type": "Soft"}, message_id="shared-id")
    )
    await asyncio.sleep(0)
    first_pending = conn.pending["shared-id"]

    with pytest.raises(ValueError, match="message ID 'shared-id' is already pending"):
        await conn.call("Reset", {"type": "Hard"}, message_id="shared-id")

    send_text = cast(AsyncMock, conn.websocket.send_text)
    send_text.assert_awaited_once()
    assert conn.pending["shared-id"] is first_pending
    await transport.handle_message(
        conn, encode_frame(Frame(3, "shared-id", {"status": "Accepted"}))
    )
    assert await first_call == Frame(3, "shared-id", {"status": "Accepted"})
    assert conn.pending == {}


@pytest.mark.asyncio
async def test_distinct_pending_message_ids_match_out_of_order_replies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = connection()
    monkeypatch.setattr(transport, "record_contact", AsyncMock())
    first_call = asyncio.create_task(
        conn.call("Reset", {"type": "Soft"}, message_id="first-id")
    )
    second_call = asyncio.create_task(
        conn.call("Reset", {"type": "Hard"}, message_id="second-id")
    )
    await asyncio.sleep(0)
    sent = cast(AsyncMock, conn.websocket.send_text).await_args_list
    assert {decode_frame(call.args[0]).message_id for call in sent} == {
        "first-id",
        "second-id",
    }

    second_reply = Frame(3, "second-id", {"result": "second"})
    await transport.handle_message(conn, encode_frame(second_reply))
    assert await second_call == second_reply
    assert not first_call.done()

    first_reply = Frame(3, "first-id", {"result": "first"})
    await transport.handle_message(conn, encode_frame(first_reply))
    assert await first_call == first_reply
    assert conn.pending == {}


@pytest.mark.asyncio
async def test_server_call_timeout_cleans_pending() -> None:
    conn = connection()
    with pytest.raises(TimeoutError):
        await conn.call("Reset", {}, timeout=0.001)
    assert not conn.pending


@pytest.mark.asyncio
async def test_inflight_reply_stays_on_old_socket(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = OcppConnectionRegistry()
    old = connection()
    new = connection(old.charge_point_id, old.station_id)
    await registry.replace(old)
    started, release = asyncio.Event(), asyncio.Event()

    async def delayed_dispatch(
        conn: OcppConnection, frame: Frame, *, record_seen: bool = False
    ) -> str:
        started.set()
        await release.wait()
        return encode_frame(Frame(3, frame.message_id, {}))

    monkeypatch.setattr(transport, "dispatch_call", delayed_dispatch)
    task = asyncio.create_task(
        transport.handle_message(old, '[2,"old-call","Test",{}]')
    )
    await started.wait()
    await registry.replace(new)
    release.set()
    await task
    cast(AsyncMock, old.websocket.send_text).assert_awaited_once_with(
        '[3,"old-call",{}]'
    )
    cast(AsyncMock, new.websocket.send_text).assert_not_awaited()
    await registry.remove(old.charge_point_code, old.websocket)
    assert await registry.get(new.charge_point_code) is new


async def charger_fixture(
    session: AsyncSession, status: str = "active"
) -> tuple[Station, ChargePoint]:
    user = User(email=f"ocpp-{uuid4()}@example.com", password_hash="unused")
    session.add(user)
    await session.flush()
    station = Station(
        owner_id=user.id,
        name="OCPP fixture",
        address="Test",
        latitude=Decimal("10.7"),
        longitude=Decimal("106.7"),
        status=status,
    )
    session.add(station)
    await session.flush()
    charger = ChargePoint(station_id=station.id, code=f"test-{uuid4()}")
    session.add(charger)
    await session.flush()
    return station, charger


@pytest.mark.asyncio
async def test_boot_duplicate_survives_new_connection_and_changes_no_metadata(
    db_session: AsyncSession, caplog: pytest.LogCaptureFixture
) -> None:
    station, charger = await charger_fixture(db_session)
    conn = connection(charger.id, station.id)
    boot = Frame(
        2,
        "boot-id",
        {
            "chargePointVendor": "Vendor",
            "chargePointModel": "Model",
            "firmwareVersion": "1.0",
        },
        action="BootNotification",
    )
    first = await process_call(conn, boot, db_session)
    boot_time = charger.last_boot_at
    assert json.loads(first)[2]["status"] == "Accepted"
    assert conn.boot_accepted and charger.vendor == "Vendor"
    fresh = connection(charger.id, station.id)
    assert await process_call(fresh, boot, db_session) == first
    assert fresh.boot_accepted and charger.last_boot_at == boot_time
    changed = Frame(
        2,
        "boot-id",
        {"chargePointVendor": "Changed", "chargePointModel": "Other"},
        action="BootNotification",
    )
    assert await process_call(fresh, changed, db_session) == first
    assert charger.vendor == "Vendor"
    assert "ocpp_duplicate_payload_mismatch" in caplog.text
    assert (
        len(
            (
                await db_session.scalars(
                    select(OcppMessageReply).where(
                        OcppMessageReply.charge_point_id == charger.id
                    )
                )
            ).all()
        )
        == 1
    )


@pytest.mark.asyncio
async def test_boot_gate_blocked_station_and_unsupported_action(
    db_session: AsyncSession,
) -> None:
    station, charger = await charger_fixture(db_session, "blocked")
    conn = connection(charger.id, station.id)
    assert (
        decode_frame(
            await process_call(
                conn, Frame(2, "before", {}, action="Heartbeat"), db_session
            )
        ).error_code
        == "SecurityError"
    )
    reply = decode_frame(
        await process_call(
            conn,
            Frame(
                2,
                "blocked",
                {"chargePointVendor": "V", "chargePointModel": "M"},
                action="BootNotification",
            ),
            db_session,
        )
    )
    assert reply.payload["status"] == "Rejected" and not conn.boot_accepted
    assert charger.status != "online"
    station.status = "suspended"
    reply = decode_frame(
        await process_call(
            conn,
            Frame(
                2,
                "suspended",
                {"chargePointVendor": "V", "chargePointModel": "M"},
                action="BootNotification",
            ),
            db_session,
        )
    )
    assert reply.payload["status"] == "Accepted"
    assert (
        decode_frame(
            await process_call(
                conn, Frame(2, "unknown", {}, action="UnknownAction"), db_session
            )
        ).error_code
        == "NotImplemented"
    )


@pytest.mark.asyncio
async def test_unsupported_action_is_logged_at_default_level_after_boot(
    db_session: AsyncSession,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    station, charger = await charger_fixture(db_session)
    conn = connection(charger.id, station.id)
    conn.charge_point_code = charger.code

    async def dispatch_with_test_session(
        current: OcppConnection, frame: Frame, *, record_seen: bool = False
    ) -> str:
        return await process_call(
            current, frame, db_session, record_seen=record_seen
        )

    monkeypatch.setattr(transport, "record_contact", AsyncMock())
    monkeypatch.setattr(transport, "dispatch_call", dispatch_with_test_session)

    ocpp_logger = logging.getLogger("csms.ocpp")
    assert ocpp_logger.getEffectiveLevel() >= logging.WARNING

    await transport.handle_message(
        conn,
        '[2,"boot-id","BootNotification",'
        '{"chargePointVendor":"V","chargePointModel":"M"}]',
    )
    boot_reply = decode_frame(
        cast(AsyncMock, conn.websocket.send_text).await_args.args[0]
    )
    assert boot_reply.payload["status"] == "Accepted"

    await transport.handle_message(
        conn, '[2,"unsupported-id","FirmwareStatusNotification",{}]'
    )
    unsupported_reply = decode_frame(
        cast(AsyncMock, conn.websocket.send_text).await_args.args[0]
    )
    assert unsupported_reply.kind == 4
    assert unsupported_reply.error_code == "NotImplemented"
    assert unsupported_reply.message_id == "unsupported-id"

    matching_logs = [
        record
        for record in caplog.records
        if record.name == "csms.ocpp"
        and "ocpp_action_not_implemented" in record.getMessage()
    ]
    assert len(matching_logs) == 1
    assert matching_logs[0].levelno >= logging.WARNING
    assert f"charge_point_code={charger.code}" in matching_logs[0].getMessage()
    assert "message_id=unsupported-id" in matching_logs[0].getMessage()
    assert "action=FirmwareStatusNotification" in matching_logs[0].getMessage()


@pytest.mark.asyncio
async def test_invalid_boot_and_reply_retention(db_session: AsyncSession) -> None:
    station, charger = await charger_fixture(db_session)
    conn = connection(charger.id, station.id)
    reply = decode_frame(
        await process_call(
            conn,
            Frame(2, "invalid", {"chargePointVendor": "V"}, action="BootNotification"),
            db_session,
        )
    )
    assert reply.kind == 4 and not conn.boot_accepted
    cached = await db_session.get(OcppMessageReply, (charger.id, "invalid"))
    assert cached is not None
    cached.created_at = datetime.now(UTC) - timedelta(days=8)
    await db_session.flush()
    await prune_replies(db_session)
    await db_session.flush()
    assert (
        await db_session.scalar(
            select(OcppMessageReply).where(
                OcppMessageReply.charge_point_id == charger.id
            )
        )
    ) is None


def test_real_websocket_keeps_open_after_malformed_frame(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(transport, "record_contact", AsyncMock())
    monkeypatch.setattr(
        ocpp_router,
        "find_registered_charge_point",
        AsyncMock(return_value=RegisteredChargePoint(uuid4(), uuid4(), "active")),
    )
    monkeypatch.setattr(ocpp_router, "ocpp_connections", OcppConnectionRegistry())
    monkeypatch.setattr(
        transport,
        "dispatch_call",
        AsyncMock(return_value='[3,"boot",{"status":"Accepted"}]'),
    )
    with (
        TestClient(app) as client,
        client.websocket_connect(
            "/ocpp/cp-test", subprotocols=["ocpp1.6"]
        ) as websocket,
    ):
        websocket.send_text('[2,"malformed","BootNotification"]')
        assert websocket.receive_json()[:3] == [4, "malformed", "FormationViolation"]
        websocket.send_text(
            '[2,"boot","BootNotification",{"chargePointVendor":"V","chargePointModel":"M"}]'
        )
        assert websocket.receive_json()[:2] == [3, "boot"]


@pytest.mark.asyncio
async def test_monitor_owner_scope_and_driver_denied(db_session: AsyncSession) -> None:
    from httpx import ASGITransport, AsyncClient

    station, charger = await charger_fixture(db_session)
    other_station, _ = await charger_fixture(db_session)
    actor = CurrentActor(station.owner_id, frozenset({"station_owner"}))

    async def database_override():
        yield db_session

    app.dependency_overrides[get_db_session] = database_override
    app.dependency_overrides[get_current_actor] = lambda: actor
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/api/v1/ocpp/connections")
            assert response.status_code == 200
            assert [item["id"] for item in response.json()["items"]] == [
                str(charger.id)
            ]
            assert other_station.owner_id != station.owner_id
            assert response.json()["items"][0]["connected"] is False
            actor = CurrentActor(uuid4(), frozenset({"driver"}))
            assert (await client.get("/api/v1/ocpp/connections")).status_code == 403
    finally:
        app.dependency_overrides.clear()
