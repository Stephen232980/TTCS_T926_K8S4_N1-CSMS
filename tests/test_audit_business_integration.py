from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from src.modules.charging import recovery
from src.modules.charging.models import ChargingSession, ChargingSessionEvent
from src.modules.identity.authorization import AuthorizationEvidence
from src.modules.ocpp import control
from src.modules.ocpp.control_models import ControlRequest, ControlResult
from src.platform.audit.models import AuditLog
from tests.test_charging_sessions import call, meter_payload, start
from tests.test_ocpp_control import db_session as _control_database
from tests.test_ocpp_control import fixture, reply_with

db_session = _control_database


async def audit_rows(session, actor_id):
    return (
        await session.scalars(select(AuditLog).where(AuditLog.actor_id == actor_id))
    ).all()


async def test_reset_and_stop_have_exactly_two_rows_and_results_join(db_session):
    station, charger, conn, tag = await fixture(db_session)
    tid = (await start(db_session, conn, tag)).payload["transactionId"]
    await db_session.commit()
    reply_with(conn)
    for action, target, permission in (
        ("Reset", charger.id, "ops.connector.reset"),
        ("RemoteStopTransaction", tid, "ops.session.stop"),
    ):
        request_id = uuid4()
        evidence = AuthorizationEvidence(permission, ("operator", "admin"))
        result = await control.execute_command(
            station.owner_id, request_id, action, target, authorization=evidence
        )
        assert result["status"] == "Accepted"
        assert (
            await control.execute_command(
                station.owner_id, request_id, action, target, authorization=evidence
            )
            == result
        )
    rows = await audit_rows(db_session, station.owner_id)
    assert len(rows) == 2
    assert {row.action for row in rows} == {"ocpp.reset", "ocpp.remote_stop"}
    for row in rows:
        assert set(row.data) == {"request_id"}
        request = await db_session.get(ControlRequest, row.data["request_id"])
        result = await db_session.get(ControlResult, request.id)
        assert result.status == "Accepted"
        assert row.permission == request.permission
        assert row.actor_roles == ["admin", "operator"]
        assert row.occurred_at is not None
        assert row.object_type == (
            "charge_point" if request.action == "Reset" else "charging_session"
        )
        assert row.object_id == str(charger.id if request.action == "Reset" else tid)
    assert conn.websocket.send_text.await_count == 2
    assert (await db_session.get(ChargingSession, tid)).ended_at is None


@pytest.mark.parametrize("action", ["Reset", "RemoteStopTransaction"])
@pytest.mark.parametrize("after_audit", [False, True])
async def test_command_audit_failure_rolls_back_request_and_never_sends(
    db_session, monkeypatch, action, after_audit
):
    station, charger, conn, tag = await fixture(db_session)
    target = charger.id
    if action == "RemoteStopTransaction":
        target = (await start(db_session, conn, tag)).payload["transactionId"]
        await db_session.commit()
    reply_with(conn)
    original = control.ghi_nhat_ky

    async def fail(session, **kwargs):
        # Before audit: request already flushed. After audit: both rows flushed.
        if after_audit:
            await original(session, **kwargs)
        raise RuntimeError("injected audit failure")

    monkeypatch.setattr(control, "ghi_nhat_ky", fail)
    request_id = uuid4()
    with pytest.raises(RuntimeError, match="injected audit failure"):
        await control.execute_command(station.owner_id, request_id, action, target)
    assert await db_session.get(ControlRequest, request_id) is None
    assert await db_session.get(ControlResult, request_id) is None
    assert await audit_rows(db_session, station.owner_id) == []
    conn.websocket.send_text.assert_not_awaited()


@pytest.mark.parametrize("outcome", ["Offline", "Timeout", "Rejected"])
async def test_failed_or_unanswered_command_keeps_one_audit(
    db_session, monkeypatch, outcome
):
    station, charger, conn, _ = await fixture(db_session)
    reply_with(conn, outcome)
    if outcome == "Offline":
        conn.boot_accepted = False
    elif outcome == "Timeout":
        from unittest.mock import AsyncMock

        conn.websocket.send_text = AsyncMock()
        monkeypatch.setattr(control, "COMMAND_TIMEOUT", 0.01)
    request_id = uuid4()
    assert (
        await control.execute_command(station.owner_id, request_id, "Reset", charger.id)
    )["status"] == outcome
    rows = await audit_rows(db_session, station.owner_id)
    assert len(rows) == 1
    assert rows[0].data == {"request_id": str(request_id)}
    assert (await db_session.get(ControlResult, request_id)).status == outcome


async def test_audit_is_present_before_socket_send_and_key_conflict_adds_no_row(
    db_session, monkeypatch
):
    station, charger, _conn, _ = await fixture(db_session)
    request_id = uuid4()

    async def send(*args):
        async with control.SessionFactory() as session:
            assert await session.get(ControlRequest, request_id) is not None
            rows = await audit_rows(session, station.owner_id)
            assert len(rows) == 1 and rows[0].data == {"request_id": str(request_id)}
        return "Accepted"

    monkeypatch.setattr(control, "send_command", send)
    await control.execute_command(station.owner_id, request_id, "Reset", charger.id)
    with pytest.raises(HTTPException) as error:
        await control.execute_command(
            station.owner_id, request_id, "Reset", charger.id, "Hard"
        )
    assert error.value.status_code == 409
    assert len(await audit_rows(db_session, station.owner_id)) == 1


async def test_result_failure_keeps_request_audit_and_deadline_adds_no_audit(
    db_session, monkeypatch
):
    station, charger, conn, _ = await fixture(db_session)
    reply_with(conn)
    original = control.record_result

    async def fail(*args):
        raise RuntimeError("result storage failed")

    monkeypatch.setattr(control, "record_result", fail)
    request_id = uuid4()
    with pytest.raises(RuntimeError, match="result storage failed"):
        await control.execute_command(station.owner_id, request_id, "Reset", charger.id)
    assert await db_session.get(ControlResult, request_id) is None
    rows = await audit_rows(db_session, station.owner_id)
    assert len(rows) == 1
    assert (
        await control.execute_command(station.owner_id, request_id, "Reset", charger.id)
    )["status"] == "Pending"
    monkeypatch.setattr(control, "record_result", original)
    request = await db_session.get(ControlRequest, request_id)
    await control.scan_control_deadlines(
        db_session, request.created_at + timedelta(seconds=32)
    )
    assert (await db_session.get(ControlResult, request_id)).status == "Timeout"
    assert len(await audit_rows(db_session, station.owner_id)) == 1
    conn.websocket.send_text.assert_awaited_once()


async def abnormal_session(session):
    station, _, conn, tag = await fixture(session)
    stamp = datetime.now(UTC) - timedelta(minutes=10)
    tid = (await start(session, conn, tag, stamp)).payload["transactionId"]
    transaction = await session.get(ChargingSession, tid)
    transaction.abnormal_since = stamp
    await call(
        session,
        conn,
        "MeterValues",
        meter_payload(tid, stamp + timedelta(seconds=30), 3500),
    )
    await session.flush()
    return station.owner_id, transaction


async def test_manual_close_references_event_once_without_copying_reason(db_session):
    actor_id, transaction = await abnormal_session(db_session)
    await recovery.manual_close(
        db_session,
        transaction,
        actor_id,
        "Checked by staff user@example.com",
        authorization=AuthorizationEvidence("ops.sessions.close", ("operator",)),
    )
    rows = await audit_rows(db_session, actor_id)
    assert len(rows) == 1
    row = rows[0]
    assert row.action == "charging.manual_close"
    assert row.object_type == "charging_session" and row.object_id == str(
        transaction.id
    )
    assert row.permission == "ops.sessions.close" and row.actor_roles == ["operator"]
    assert set(row.data) == {"event_id"}
    event = await db_session.get(ChargingSessionEvent, row.data["event_id"])
    assert event.session_id == transaction.id and event.actor_id == actor_id
    assert event.details["reason"] == "Checked by staff user@example.com"
    with pytest.raises(HTTPException):
        await recovery.manual_close(db_session, transaction, actor_id, "Again")
    assert len(await audit_rows(db_session, actor_id)) == 1


@pytest.mark.parametrize("after_audit", [False, True])
async def test_manual_close_audit_failure_rolls_back_event_and_session(
    db_session, monkeypatch, after_audit
):
    actor_id, transaction = await abnormal_session(db_session)
    tid = transaction.id
    original = recovery.ghi_nhat_ky

    async def fail(session, **kwargs):
        if after_audit:
            await original(session, **kwargs)
        raise RuntimeError("injected audit failure")

    monkeypatch.setattr(recovery, "ghi_nhat_ky", fail)
    with pytest.raises(RuntimeError, match="injected audit failure"):
        await recovery.manual_close(db_session, transaction, actor_id, "Checked")
    await db_session.refresh(transaction)
    assert transaction.ended_at is None and transaction.abnormal_since is not None
    assert transaction.closed_by is None and transaction.energy_kwh is None
    assert await audit_rows(db_session, actor_id) == []
    assert (
        await db_session.scalars(
            select(ChargingSessionEvent).where(
                ChargingSessionEvent.session_id == tid,
                ChargingSessionEvent.action == "manual_closure",
            )
        )
    ).all() == []


async def test_manual_close_participates_in_caller_rollback(db_session):
    actor_id, transaction = await abnormal_session(db_session)
    with pytest.raises(RuntimeError):
        async with db_session.begin_nested():
            await recovery.manual_close(db_session, transaction, actor_id, "Checked")
            assert len(await audit_rows(db_session, actor_id)) == 1
            raise RuntimeError("business transaction failed")
    await db_session.refresh(transaction)
    assert transaction.ended_at is None
    assert await audit_rows(db_session, actor_id) == []
