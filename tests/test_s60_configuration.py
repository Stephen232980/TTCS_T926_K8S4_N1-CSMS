import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from src.entrypoints.http import app
from src.modules.identity.authorization import AuthorizationEvidence, CurrentActor
from src.modules.identity.dependencies import get_current_actor
from src.modules.ocpp import configuration as service
from src.modules.ocpp.configuration_adapter import configuration_call
from src.modules.ocpp.configuration_models import ConfigurationIntent
from src.modules.ocpp.connection_registry import ocpp_connections
from src.modules.ocpp.frames import Frame, decode_frame
from src.modules.stations.models import ChargePoint, Connector
from src.platform.audit.models import AuditLog
from src.platform.database.session import get_db_session
from tests.test_charging_sessions import setup, start
from tests.test_wallet_service import isolated_wallet_db  # noqa: F401

EVIDENCE = AuthorizationEvidence("ops.configuration.change", ("operator",))


@pytest.fixture
async def fleet(isolated_wallet_db, monkeypatch):  # noqa: F811
    factory = isolated_wallet_db
    monkeypatch.setattr(service, "SessionFactory", factory)
    async with factory() as db:
        station, point, _connector, _driver, _card, conn, tag = await setup(db)
        point.last_seen_at = datetime.now(UTC)
        point.heartbeat_interval_seconds = 30
        conn.charge_point_code = point.code.lower()
        await db.commit()
    await ocpp_connections.replace(conn)
    actor = CurrentActor(station.owner_id, frozenset({"operator"}))

    async def database():
        async with factory() as db:
            yield db
            await db.commit()

    app.dependency_overrides[get_db_session] = database
    values = {"HeartbeatInterval": "30", "MeterValueSampleInterval": "10"}
    calls = []
    settings = {
        "change": "Accepted",
        "mismatch": False,
        "readonly": False,
        "unknown": False,
        "reset": "Accepted",
        "read_timeout": False,
    }

    async def answer(raw):
        frame = decode_frame(raw)
        calls.append((frame.action, frame.payload))
        if frame.action == "GetConfiguration":
            if settings["read_timeout"]:
                conn.pending[frame.message_id].set_exception(TimeoutError())
                return
            payload = {"configurationKey": [], "unknownKey": []}
            for key in frame.payload["key"]:
                if settings["unknown"]:
                    payload["unknownKey"].append(key)
                else:
                    payload["configurationKey"].append(
                        {
                            "key": key,
                            "readonly": settings["readonly"],
                            "value": values[key],
                        }
                    )
        elif frame.action == "ChangeConfiguration":
            if settings["change"] == "Timeout":
                conn.pending[frame.message_id].set_exception(TimeoutError())
                return
            if settings["change"] == "Disconnected":
                conn.pending[frame.message_id].set_exception(ConnectionError())
                return
            payload = {"status": settings["change"]}
            if settings["change"] == "Accepted" and not settings["mismatch"]:
                values[frame.payload["key"]] = frame.payload["value"]
        else:
            payload = {"status": settings["reset"]}
            if settings["reset"] == "Accepted":
                values["HeartbeatInterval"] = "60"
        conn.pending[frame.message_id].set_result(Frame(3, frame.message_id, payload))

    conn.websocket.send_text = AsyncMock(side_effect=answer)
    try:
        yield SimpleNamespace(
            factory=factory,
            point=point,
            actor=actor,
            conn=conn,
            values=values,
            calls=calls,
            settings=settings,
            tag=tag,
        )
    finally:
        app.dependency_overrides.clear()
        await ocpp_connections.remove(conn.charge_point_code, conn.websocket)


async def submit(fleet, identifier=None, key="HeartbeatInterval", value=60):
    identifier = identifier or uuid4()
    async with fleet.factory() as db:
        row = await service.submit(
            db, fleet.point.id, identifier, fleet.actor.user_id, key, value, EVIDENCE
        )
        await db.commit()
        return row


async def stored(fleet, identifier):
    async with fleet.factory() as db:
        return await db.get(ConfigurationIntent, identifier)


async def due(fleet, identifier):
    async with fleet.factory() as db, db.begin():
        row = await db.get(ConfigurationIntent, identifier)
        row.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)


async def test_durable_replay_verified_heartbeat_and_audit(fleet):
    row = await submit(fleet)
    assert fleet.calls == []
    assert (await submit(fleet, row.id)).id == row.id
    async with fleet.factory() as db:
        with pytest.raises(HTTPException) as error:
            await service.submit(
                db,
                fleet.point.id,
                row.id,
                fleet.actor.user_id,
                "HeartbeatInterval",
                90,
                EVIDENCE,
            )
        assert error.value.status_code == 409
        assert (
            await db.get(ChargePoint, fleet.point.id)
        ).heartbeat_interval_seconds == 30
    await asyncio.gather(service.process(row.id), service.process(row.id))
    result = await stored(fleet, row.id)
    assert (
        result.state == "verified"
        and result.actual_value == "60"
        and result.old_value == "30"
    )
    assert [a for a, _ in fleet.calls].count("ChangeConfiguration") == 1
    assert (await submit(fleet, row.id)).state == "verified"
    async with fleet.factory() as db:
        assert (
            await db.get(ChargePoint, fleet.point.id)
        ).heartbeat_interval_seconds == 60
        audits = (
            await db.scalars(
                select(AuditLog).where(AuditLog.object_id == str(fleet.point.id))
            )
        ).all()
        assert any(
            a.action == "ocpp.configuration_dispatch" and a.data["old_value"] == "30"
            for a in audits
        )
        assert sum(a.action == "ocpp.configuration_requested" for a in audits) == 1
    from unittest.mock import patch

    from src.modules.ocpp import dispatcher

    with patch.object(dispatcher, "SessionFactory", fleet.factory):
        reply = await dispatcher.dispatch_call(
            fleet.conn,
            Frame(
                2,
                str(uuid4()),
                {"chargePointVendor": "QA", "chargePointModel": "S60"},
                action="BootNotification",
            ),
        )
    assert decode_frame(reply).payload["interval"] == 60
    async with fleet.factory() as db:
        assert (
            await db.get(ChargePoint, fleet.point.id)
        ).heartbeat_interval_seconds == 60


@pytest.mark.parametrize(
    "status,state",
    [
        ("Rejected", "failed"),
        ("NotSupported", "failed"),
        ("Bogus", "failed"),
        ("Timeout", "needs_review"),
        ("Disconnected", "needs_review"),
    ],
)
async def test_outcomes_do_not_claim_success_or_change_liveness(fleet, status, state):
    fleet.settings["change"] = status
    row = await submit(fleet)
    await service.process(row.id)
    assert (await stored(fleet, row.id)).state == state
    async with fleet.factory() as db:
        assert (
            await db.get(ChargePoint, fleet.point.id)
        ).heartbeat_interval_seconds == 30


async def test_mismatch_and_readonly_unknown_do_not_verify(fleet):
    fleet.settings["mismatch"] = True
    row = await submit(fleet)
    await service.process(row.id)
    result = await stored(fleet, row.id)
    assert result.state == "needs_review" and result.actual_value == "30"
    for mode in ["readonly", "unknown"]:
        fleet.settings[mode] = True
        row = await submit(fleet)
        before = len(fleet.calls)
        await service.process(row.id)
        assert (await stored(fleet, row.id)).state == "failed"
        assert all(
            action != "ChangeConfiguration" for action, _ in fleet.calls[before:]
        )
        fleet.settings[mode] = False


async def test_reboot_is_explicit_and_reconnect_readback_updates_heartbeat(fleet):
    fleet.settings["change"] = "RebootRequired"
    row = await submit(fleet)
    await service.process(row.id)
    assert (await stored(fleet, row.id)).state == "reboot_required"
    assert not any(a == "Reset" for a, _ in fleet.calls)
    async with fleet.factory() as db:
        await service.request_reset(
            db, fleet.point.id, row.id, uuid4(), fleet.actor.user_id, EVIDENCE
        )
        await db.commit()
    async with fleet.factory() as db:
        from src.modules.charging.service import authorize
        from src.modules.ocpp.configuration_gate import reset_pending

        assert await reset_pending(db, fleet.point.id)
        point = await db.get(ChargePoint, fleet.point.id)
        assert (await authorize(db, point, fleet.tag))[0] == "Blocked"
    await service.process(row.id)
    assert [a for a, _ in fleet.calls].count("Reset") == 1
    await due(fleet, row.id)
    await service.process(row.id)
    assert (await stored(fleet, row.id)).state == "verified"
    async with fleet.factory() as db:
        assert not await reset_pending(db, fleet.point.id)


async def test_reset_blocked_during_charging(fleet):
    fleet.settings["change"] = "RebootRequired"
    row = await submit(fleet)
    await service.process(row.id)
    async with fleet.factory() as db:
        result = await start(db, fleet.conn, fleet.tag)
        assert result.payload["idTagInfo"]["status"] == "Accepted"
        await db.commit()
    async with fleet.factory() as db:
        with pytest.raises(HTTPException) as error:
            await service.request_reset(
                db, fleet.point.id, row.id, uuid4(), fleet.actor.user_id, EVIDENCE
            )
        assert error.value.status_code == 409
    assert not any(a == "Reset" for a, _ in fleet.calls)


@pytest.mark.parametrize(
    "status", ["Preparing", "Charging", "SuspendedEV", "SuspendedEVSE", "Finishing"]
)
async def test_reset_blocked_by_reported_busy_connector_without_session(fleet, status):
    fleet.settings["change"] = "RebootRequired"
    row = await submit(fleet)
    await service.process(row.id)
    async with fleet.factory() as db:
        connector = await db.scalar(
            select(Connector).where(Connector.charge_point_id == fleet.point.id)
        )
        connector.raw_ocpp_status = status
        await db.commit()
        with pytest.raises(HTTPException) as error:
            await service.request_reset(
                db, fleet.point.id, row.id, uuid4(), fleet.actor.user_id, EVIDENCE
            )
        assert error.value.status_code == 409
    assert not any(action == "Reset" for action, _ in fleet.calls)


async def test_archived_charger_does_not_stall_worker_or_send_configuration(fleet):
    row = await submit(fleet)
    async with fleet.factory() as db:
        point = await db.get(ChargePoint, fleet.point.id)
        point.archived_at = datetime.now(UTC)
        await db.commit()
    await service.process(row.id)
    result = await stored(fleet, row.id)
    assert (result.state, result.outcome) == ("failed", "Archived")
    assert fleet.calls == []


async def test_reset_cannot_reuse_a_change_message_id(fleet):
    fleet.settings["change"] = "RebootRequired"
    row = await submit(fleet)
    await service.process(row.id)
    async with fleet.factory() as db:
        with pytest.raises(HTTPException) as error:
            await service.request_reset(
                db, fleet.point.id, row.id, row.id, fleet.actor.user_id, EVIDENCE
            )
        assert error.value.status_code == 409


async def test_restart_never_resends_uncertain_write(fleet):
    row = await submit(fleet)
    async with fleet.factory() as db, db.begin():
        pending = await db.get(ConfigurationIntent, row.id)
        pending.state = "sending"
        pending.old_value = "30"
    fleet.values["HeartbeatInterval"] = "60"
    await service.process(row.id)
    assert (await stored(fleet, row.id)).state == "verified"
    assert [a for a, _ in fleet.calls] == ["GetConfiguration"]


async def test_readback_in_flight_cannot_overwrite_a_confirmed_reset(
    fleet, monkeypatch
):
    fleet.settings["change"] = "RebootRequired"
    row = await submit(fleet)
    await service.process(row.id)
    await due(fleet, row.id)
    entered, release = asyncio.Event(), asyncio.Event()
    original = service.read

    async def paused(conn, keys):
        result = await original(conn, keys)
        entered.set()
        await release.wait()
        return result

    monkeypatch.setattr(service, "read", paused)
    task = asyncio.create_task(service.process(row.id))
    await asyncio.wait_for(entered.wait(), timeout=5)
    try:
        async with fleet.factory() as db:
            await service.request_reset(
                db, fleet.point.id, row.id, uuid4(), fleet.actor.user_id, EVIDENCE
            )
            await db.commit()
    finally:
        release.set()
        await task
    result = await stored(fleet, row.id)
    assert (result.state, result.outcome) == ("resetting", "ResetQueued")
    monkeypatch.setattr(service, "read", original)
    await service.process(row.id)
    assert [action for action, _ in fleet.calls].count("Reset") == 1


@pytest.mark.parametrize("outcome", ["Timeout", "Disconnected", "ProtocolError"])
async def test_uncertain_reset_keeps_start_gate_and_never_resends(
    fleet, monkeypatch, outcome
):
    from src.modules.ocpp.configuration_gate import reset_pending

    fleet.settings["change"] = "RebootRequired"
    row = await submit(fleet)
    await service.process(row.id)
    async with fleet.factory() as db:
        await service.request_reset(
            db, fleet.point.id, row.id, uuid4(), fleet.actor.user_id, EVIDENCE
        )
        await db.commit()
    original = service.configuration_call
    resets = []

    async def uncertain(conn, action, payload, identifier):
        if action == "Reset":
            resets.append(identifier)
            return outcome, {}
        return await original(conn, action, payload, identifier)

    monkeypatch.setattr(service, "configuration_call", uncertain)
    await service.process(row.id)
    async with fleet.factory() as db:
        assert await reset_pending(db, fleet.point.id)
    await due(fleet, row.id)
    await service.process(row.id)
    assert len(resets) == 1
    assert (await stored(fleet, row.id)).state == "resetting"


async def test_reboot_does_not_overwrite_pending_new_heartbeat(fleet, monkeypatch):
    from src.modules.ocpp import dispatcher

    fleet.settings["change"] = "RebootRequired"
    row = await submit(fleet, value=90)
    await service.process(row.id)
    async with fleet.factory() as db:
        await service.request_reset(
            db, fleet.point.id, row.id, uuid4(), fleet.actor.user_id, EVIDENCE
        )
        await db.commit()
    await service.process(row.id)
    fleet.values["HeartbeatInterval"] = "90"
    monkeypatch.setattr(dispatcher, "SessionFactory", fleet.factory)
    reply = await dispatcher.dispatch_call(
        fleet.conn,
        Frame(
            2,
            str(uuid4()),
            {"chargePointVendor": "QA", "chargePointModel": "S60"},
            action="BootNotification",
        ),
    )
    assert decode_frame(reply).payload["interval"] == 90
    async with fleet.factory() as db:
        assert (
            await db.get(ChargePoint, fleet.point.id)
        ).heartbeat_interval_seconds == 30
    await due(fleet, row.id)
    await service.process(row.id)
    assert (await stored(fleet, row.id)).state == "verified"


async def test_whitelist_api_permissions_and_status_poll(fleet):
    app.dependency_overrides[get_current_actor] = lambda: fleet.actor
    path = f"/api/v1/ops/charge-points/{fleet.point.id}/configuration"
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        for key, value in [
            ("Unknown", 30),
            ("HeartbeatInterval", 29),
            ("HeartbeatInterval", 601),
            ("MeterValueSampleInterval", 4),
            ("MeterValueSampleInterval", 301),
            ("HeartbeatInterval", True),
            ("HeartbeatInterval", "60"),
        ]:
            response = await client.post(
                path, json={"request_id": str(uuid4()), "key": key, "value": value}
            )
            assert response.status_code == 422
        assert fleet.calls == []
        for role in ["driver", "station_owner", "accountant", "admin"]:
            app.dependency_overrides[get_current_actor] = lambda role=role: (
                CurrentActor(fleet.actor.user_id, frozenset({role}))
            )
            assert (await client.get(path)).status_code == 403
            assert (
                await client.post(
                    path,
                    json={
                        "request_id": str(uuid4()),
                        "key": "HeartbeatInterval",
                        "value": 60,
                    },
                )
            ).status_code == 403
        app.dependency_overrides[get_current_actor] = lambda: fleet.actor
        assert (await client.get(path)).status_code == 200
        before = len(fleet.calls)
        assert (await client.get(path + "?refresh=false")).status_code == 200
        assert len(fleet.calls) == before
        for confirm in [False, 1, "true", None]:
            result = await client.post(
                path + "/reset",
                json={
                    "request_id": str(uuid4()),
                    "intent_id": str(uuid4()),
                    "confirm": confirm,
                },
            )
            assert result.status_code == 422
        assert len(fleet.calls) == before


async def test_readback_timeout_retains_old_interval_until_poll_recovers(fleet):
    row = await submit(fleet)
    original = service.read
    count = 0

    async def intermittent(conn, keys):
        nonlocal count
        count += 1
        if count == 2:
            return "Timeout", None
        return await original(conn, keys)

    from unittest.mock import patch

    with patch.object(service, "read", intermittent):
        await service.process(row.id)
    assert (await stored(fleet, row.id)).state == "accepted"
    async with fleet.factory() as db:
        assert (
            await db.get(ChargePoint, fleet.point.id)
        ).heartbeat_interval_seconds == 30
    await due(fleet, row.id)
    await service.process(row.id)
    assert (await stored(fleet, row.id)).state == "verified"


@pytest.mark.parametrize(
    "reply",
    [
        {"status": "Accepted"},
        {
            "configurationKey": [
                {"key": "HeartbeatInterval", "readonly": "false", "value": "60"}
            ]
        },
        {
            "configurationKey": [
                {"key": "HeartbeatInterval", "readonly": False, "value": "60"}
            ]
            * 2
        },
    ],
)
async def test_typed_adapter_rejects_malformed_get_configuration(reply):
    conn = SimpleNamespace(call=AsyncMock(return_value=Frame(3, "test", reply)))
    outcome, _ = await configuration_call(
        conn, "GetConfiguration", {"key": ["HeartbeatInterval"]}, uuid4()
    )
    assert outcome == "ProtocolError"


async def test_two_keys_over_real_websocket_and_simulator_persistence(
    fleet, tmp_path, monkeypatch
):
    from websockets.asyncio.client import connect
    from websockets.asyncio.server import serve

    from scripts import staging_demo
    from src.modules.ocpp import transport

    monkeypatch.setattr(staging_demo, "ROOT", tmp_path)
    monkeypatch.setattr(transport, "SessionFactory", fleet.factory)
    device = staging_demo.Charger({"code": "S60-QA", "fault_connector": None})
    ready = asyncio.Event()

    async def server(socket):
        fleet.conn.websocket = SimpleNamespace(send_text=socket.send)
        ready.set()
        async for raw in socket:
            await transport.handle_message(fleet.conn, raw)

    async with serve(server, "127.0.0.1", 0, subprotocols=["ocpp1.6"]) as listener:
        port = listener.sockets[0].getsockname()[1]
        async with connect(
            f"ws://127.0.0.1:{port}", subprotocols=["ocpp1.6"]
        ) as socket:
            await ready.wait()

            async def respond():
                import json

                async for raw in socket:
                    frame = decode_frame(raw)
                    if (
                        frame.action == "ChangeConfiguration"
                        and frame.payload.get("value") == "90"
                    ):
                        payload = {"status": "RebootRequired"}
                    elif frame.action == "Reset":
                        device.reservation_command(
                            "ChangeConfiguration",
                            {"key": "HeartbeatInterval", "value": "90"},
                        )
                        payload = {"status": "Accepted"}
                    else:
                        payload = device.reservation_command(
                            frame.action, frame.payload
                        )
                    await socket.send(json.dumps([3, frame.message_id, payload]))

            task = asyncio.create_task(respond())
            try:
                for key, value in [
                    ("HeartbeatInterval", 60),
                    ("MeterValueSampleInterval", 15),
                ]:
                    row = await submit(fleet, key=key, value=value)
                    await service.process(row.id)
                    assert (await stored(fleet, row.id)).state == "verified"
                row = await submit(fleet, key="HeartbeatInterval", value=90)
                await service.process(row.id)
                assert (await stored(fleet, row.id)).state == "reboot_required"
                async with fleet.factory() as db:
                    await service.request_reset(
                        db,
                        fleet.point.id,
                        row.id,
                        uuid4(),
                        fleet.actor.user_id,
                        EVIDENCE,
                    )
                    await db.commit()
                await asyncio.wait_for(service.process(row.id), timeout=10)
                assert (await stored(fleet, row.id)).outcome == "ResetAccepted"
                await due(fleet, row.id)
                await service.process(row.id)
                assert (await stored(fleet, row.id)).state == "verified"
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
    restarted = staging_demo.Charger({"code": "S60-QA", "fault_connector": None})
    assert restarted.remote_configuration == {
        "HeartbeatInterval": 90,
        "MeterValueSampleInterval": 15,
    }
