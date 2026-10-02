import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi import HTTPException, WebSocketDisconnect

from src.modules.ocpp.control import execute_command, scan_control_deadlines
from src.modules.ocpp.control_models import ControlRequest, ControlResult
from src.modules.ocpp.frames import decode_frame
from tests.test_ocpp_control import db_session as _control_database
from tests.test_ocpp_control import fixture, reply_with

db_session = _control_database


async def test_socket_disappearing_before_send_is_audited(db_session):
    station, charger, conn, _ = await fixture(db_session)
    conn.websocket.send_text.side_effect = WebSocketDisconnect(1006)
    assert (await execute_command(station.owner_id, uuid4(), "Reset", charger.id))[
        "status"
    ] == "Disconnected"
    assert not conn.pending


async def test_hard_reset_and_callerror_are_audited(db_session):
    station, charger, conn, _ = await fixture(db_session)
    reply_with(conn, kind=4)
    uid = uuid4()
    assert (await execute_command(station.owner_id, uid, "Reset", charger.id, "Hard"))[
        "status"
    ] == "ProtocolError"
    frame = decode_frame(conn.websocket.send_text.call_args.args[0])
    assert frame.payload == {"type": "Hard"}
    assert frame.message_id == str(uid)


async def test_reusing_key_for_changed_payload_is_rejected(db_session):
    station, charger, conn, _ = await fixture(db_session)
    reply_with(conn)
    uid = uuid4()
    await execute_command(station.owner_id, uid, "Reset", charger.id)
    with pytest.raises(HTTPException) as error:
        await execute_command(station.owner_id, uid, "Reset", charger.id, "Hard")
    assert error.value.status_code == 409
    conn.websocket.send_text.assert_awaited_once()


async def test_restart_marks_orphan_timeout_without_resending(db_session):
    station, charger, conn, _ = await fixture(db_session)
    now = datetime.now(UTC)
    uid = uuid4()
    db_session.add(
        ControlRequest(
            id=uid,
            actor_id=station.owner_id,
            actor_email="demo@example.com",
            charge_point_id=charger.id,
            charge_point_code=charger.code,
            action="Reset",
            payload={"type": "Soft"},
            created_at=now - timedelta(seconds=32),
        )
    )
    await db_session.flush()
    await scan_control_deadlines(db_session, now)
    assert (await db_session.get(ControlResult, uid)).status == "Timeout"
    conn.websocket.send_text.assert_not_awaited()


async def test_http_cancellation_does_not_become_disconnected(db_session):
    station, charger, conn, _ = await fixture(db_session)
    task = asyncio.create_task(
        execute_command(station.owner_id, uuid4(), "Reset", charger.id)
    )
    for _ in range(100):
        if conn.pending:
            break
        await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not conn.pending
