"""Reservation admission, protocol outcomes and conservative release in PostgreSQL."""

import asyncio
import json
import multiprocessing
import os
import socket
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.entrypoints.http import app
from src.modules.charging.driver_models import DriverVirtualTag
from src.modules.charging.models import ChargingSession
from src.modules.identity.authorization import AuthorizationEvidence, CurrentActor
from src.modules.identity.dependencies import get_current_actor
from src.modules.identity.models import Role, User, UserRole
from src.modules.ocpp.connection_registry import OcppConnection, ocpp_connections
from src.modules.ocpp.frames import Frame
from src.modules.reservations import worker
from src.modules.reservations.models import (
    Reservation,
    ReservationCapability,
    ReservationCommand,
)
from src.modules.reservations.service import cancel_reservation, create_reservation
from src.modules.stations.models import ChargePoint, Connector, Station
from src.modules.wallet.models import Wallet
from tests.test_charging_sessions import call
from tests.test_flat_tariff_api import api_db, committed_tariff_db  # noqa: F401
from tests.test_g4_station_operation_discovery import fleet as g4_fleet

fleet = g4_fleet
EVIDENCE = AuthorizationEvidence("driver.reservations.create", ("driver",))
REAL_CALL = OcppConnection.call


async def test_driver_hold_unique_across_connectors_and_projection_scope(
    reservation_fleet,
):
    factory, station, point, connector, driver, other, conn, _ = reservation_fleet
    async with factory() as db, db.begin():
        second = Connector(
            charge_point_id=point.id,
            connector_number=2,
            status="Available",
            connector_type="Type 2",
            current_type="AC",
            max_power_kw=22,
        )
        db.add(second)
        await db.flush()
    result = await book(reservation_fleet)
    reply(conn)
    await worker.cycle()
    async with factory() as db, db.begin():
        with pytest.raises(HTTPException) as rejected:
            await create_reservation(db, driver.id, uuid4(), second.id, None, EVIDENCE)
        assert rejected.value.detail == "driver_already_reserved"
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as http:
        own = (
            await http.get(f"/api/v1/driver/stations/{station.id}/connectors")
        ).json()["items"]
        owned = next(row for row in own if row["id"] == str(connector.id))
        assert (
            owned["own_reservation"] and owned["can_start"] and not owned["available"]
        )
        app.dependency_overrides[get_current_actor] = lambda: CurrentActor(
            other.id, frozenset({"driver"})
        )
        public = (
            await http.get(f"/api/v1/driver/stations/{station.id}/connectors")
        ).json()["items"]
        held = next(row for row in public if row["id"] == str(connector.id))
        assert (
            not held["own_reservation"]
            and not held["can_start"]
            and not held["available"]
        )
        assert (await request("GET")).json()["total"] == 0
    async with factory() as db:
        assert await db.scalar(select(func.count()).select_from(Reservation)) == 1
        assert (await db.get(Reservation, result.id)).status == "active"


async def test_audit_failure_rolls_back_reservation_outbox_and_identity(
    reservation_fleet, monkeypatch
):
    from unittest.mock import AsyncMock

    from src.modules.reservations import service

    factory, _, _, _, driver, *_ = reservation_fleet
    monkeypatch.setattr(
        service, "ghi_nhat_ky", AsyncMock(side_effect=RuntimeError("audit unavailable"))
    )
    with pytest.raises(RuntimeError, match="audit unavailable"):
        await book(reservation_fleet)
    async with factory() as db:
        assert await db.scalar(select(func.count()).select_from(Reservation)) == 0
        assert (
            await db.scalar(select(func.count()).select_from(ReservationCommand)) == 0
        )
        assert await db.get(DriverVirtualTag, driver.id) is None


async def test_cancel_and_start_race_has_one_terminal_winner(reservation_fleet):
    factory, _, _, _, driver, _, conn, _ = reservation_fleet
    booked = await book(reservation_fleet)
    reply(conn)
    await worker.cycle()
    async with factory() as db:
        tag = (await db.get(DriverVirtualTag, driver.id)).id_tag
    ready = asyncio.Event()

    async def cancel_racer():
        await ready.wait()
        try:
            async with factory() as db, db.begin():
                result = await cancel_reservation(
                    db, driver.id, booked.id, uuid4(), EVIDENCE
                )
                return result.status
        except HTTPException as exc:
            assert exc.detail == "reservation_consumed"
            return "consumed"

    async def start_racer():
        await ready.wait()
        async with factory() as db, db.begin():
            result = await call(
                db,
                conn,
                "StartTransaction",
                {
                    "connectorId": 1,
                    "reservationId": booked.ocpp_id,
                    "idTag": tag,
                    "meterStart": 1000,
                    "timestamp": datetime.now(UTC).isoformat(),
                },
            )
            return result.payload["transactionId"]

    cancel_task, start_task = (
        asyncio.create_task(cancel_racer()),
        asyncio.create_task(start_racer()),
    )
    ready.set()
    cancelled, transaction_id = await asyncio.wait_for(
        asyncio.gather(cancel_task, start_task), 10
    )
    async with factory() as db:
        row = await db.get(Reservation, booked.id)
        if transaction_id:
            assert (
                row.status == cancelled == "consumed"
                and row.session_id == transaction_id
            )
        else:
            assert (
                row.status == cancelled == "cancel_pending" and row.session_id is None
            )


@pytest.fixture
async def reservation_fleet(fleet, monkeypatch):
    factory, station, point, connector, driver, conn, _, now = fleet
    async with factory() as db, db.begin():
        db.add(
            ReservationCapability(
                charge_point_id=point.id,
                boot_at=point.last_boot_at,
                supported=True,
                checked_at=now,
                next_attempt_at=now,
                outcome="supported",
            )
        )
        other = User(email=f"g5-{uuid4()}@example.com", password_hash="unused")
        db.add(other)
        await db.flush()
        role = await db.scalar(select(Role).where(Role.code == "driver"))
        db.add(UserRole(user_id=other.id, role_id=role.id))
        db.add(Wallet(driver_id=other.id, balance_vnd=1_000_000, status="active"))
    conn.charge_point_code = point.code.strip().lower()
    from unittest.mock import AsyncMock

    monkeypatch.setattr(type(conn), "call", AsyncMock())
    await ocpp_connections.replace(conn)
    monkeypatch.setattr(worker, "SessionFactory", factory)
    app.dependency_overrides[get_current_actor] = lambda: CurrentActor(
        driver.id, frozenset({"driver"})
    )
    yield factory, station, point, connector, driver, other, conn, now
    await ocpp_connections.remove(conn.charge_point_code, conn.websocket)
    app.dependency_overrides.pop(get_current_actor, None)


async def request(method, path="", body=None):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        return await client.request(
            method, f"/api/v1/driver/reservations{path}", json=body
        )


async def book(fixture, key=None, actor=None):
    factory, _, _, connector, driver, *_ = fixture
    key = key or uuid4()
    async with factory() as db, db.begin():
        result = await create_reservation(
            db, actor or driver.id, key, connector.id, None, EVIDENCE
        )
    return result


def reply(conn, outcome="Accepted"):
    async def answer(action, payload, **kwargs):
        if action == "GetConfiguration":
            return Frame(
                3,
                kwargs["message_id"],
                {
                    "configurationKey": [
                        {
                            "key": "SupportedFeatureProfiles",
                            "readonly": True,
                            "value": "Core,Reservation",
                        }
                    ]
                },
            )
        return Frame(3, kwargs["message_id"], {"status": outcome})

    conn.call.side_effect = answer


async def test_request_replay_scope_hash_and_safe_public_projection(reservation_fleet):
    factory, _, _, connector, driver, other, _, _ = reservation_fleet
    key = uuid4()
    body = {
        "request_id": str(key),
        "connector_id": str(connector.id),
        "arrival_at": None,
    }
    first = await request("POST", body=body)
    second = await request("POST", body=body)
    assert first.status_code == second.status_code == 202
    assert first.json()["id"] == second.json()["id"]
    assert first.json()["status"] == "pending"
    assert (
        not {"card_id", "idTag", "driver_id", "request_hash", "ocpp_id"}
        & first.json().keys()
    )
    altered = {
        **body,
        "arrival_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
    }
    assert (await request("POST", body=altered)).status_code == 409
    app.dependency_overrides[get_current_actor] = lambda: CurrentActor(
        other.id, frozenset({"driver"})
    )
    assert (await request("POST", body=body)).status_code == 409
    assert (await request("GET", f"/{key}")).status_code == 403
    assert (
        await request("POST", f"/{key}/cancel", {"request_id": str(uuid4())})
    ).status_code == 403
    async with factory() as db:
        assert await db.scalar(select(func.count()).select_from(Reservation)) == 1
        assert (
            await db.scalar(select(func.count()).select_from(ReservationCommand)) == 1
        )
        assert (await db.get(Reservation, key)).driver_id == driver.id


@pytest.mark.parametrize(
    "outcome,expected",
    [
        ("Accepted", "active"),
        ("Occupied", "rejected"),
        ("Rejected", "rejected"),
        ("Unavailable", "rejected"),
        ("Faulted", "rejected"),
    ],
)
async def test_reserve_status_parser_and_one_wire_attempt(
    reservation_fleet, outcome, expected
):
    factory, _, _, connector, _, _, conn, _ = reservation_fleet
    result = await book(reservation_fleet)
    reply(conn, outcome)
    await worker.cycle()
    await worker.cycle()
    async with factory() as db:
        stored = await db.get(Reservation, result.id)
        assert stored.status == expected and stored.ocpp_id > 0
        assert (await db.get(Connector, connector.id)).status == "Available"
    assert conn.call.await_count == 1
    payload = conn.call.call_args.args[1]
    assert payload["connectorId"] == 1 and payload["reservationId"] == result.ocpp_id
    assert len(payload["idTag"]) <= 20 and "expiryDate" in payload


@pytest.mark.parametrize("failure", [TimeoutError, ConnectionError])
async def test_unknown_delivery_retains_hold_and_is_never_resubmitted(
    reservation_fleet, failure
):
    factory, _, _, _, _, _, conn, _ = reservation_fleet
    result = await book(reservation_fleet)
    conn.call.side_effect = failure()
    await worker.cycle()
    await worker.cycle()
    async with factory() as db:
        assert (await db.get(Reservation, result.id)).status == "uncertain"
    assert conn.call.await_count == 1
    with pytest.raises(HTTPException) as error:
        await book(reservation_fleet)
    assert error.value.detail == "connector_reserved"


async def test_cancel_before_deadline_ack_after_deadline_is_exempt_idempotent(
    reservation_fleet,
):
    factory, _, _, _, _, _, conn, _ = reservation_fleet
    result = await book(reservation_fleet)
    reply(conn)
    await worker.cycle()
    key = uuid4()
    response = await request("POST", f"/{result.id}/cancel", {"request_id": str(key)})
    assert response.status_code == 202 and response.json()["status"] == "cancel_pending"
    assert (
        await request("POST", f"/{result.id}/cancel", {"request_id": str(key)})
    ).status_code == 202
    # Simulate expiry while ACK is in flight, preserving arrival/created constraints.
    async with factory() as db, db.begin():
        stored = await db.get(Reservation, result.id)
        stored.created_at = datetime.now(UTC) - timedelta(minutes=20)
        stored.arrival_at = datetime.now(UTC) - timedelta(minutes=16)
        stored.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    await worker.cycle()
    async with factory() as db:
        stored = await db.get(Reservation, result.id)
        assert stored.status == "cancelled" and stored.no_show_exempt
        assert (
            await db.scalar(select(func.count()).select_from(ReservationCommand)) == 2
        )
    assert conn.call.await_count == 2


async def test_cancel_timeout_rejected_never_manufactures_available(reservation_fleet):
    factory, _, _, connector, _, _, conn, _ = reservation_fleet
    result = await book(reservation_fleet)
    reply(conn)
    await worker.cycle()
    async with factory() as db, db.begin():
        stored = await db.get(Connector, connector.id)
        stored.status = stored.raw_ocpp_status = "Reserved"
    conn.call.side_effect = TimeoutError()
    assert (
        await request("POST", f"/{result.id}/cancel", {"request_id": str(uuid4())})
    ).status_code == 202
    await worker.cycle()
    async with factory() as db:
        assert (await db.get(Reservation, result.id)).status == "cancel_pending"
        assert (await db.get(Connector, connector.id)).raw_ocpp_status == "Reserved"
    reply(conn, "Rejected")
    async with factory() as db, db.begin():
        command = await db.scalar(
            select(ReservationCommand).where(
                ReservationCommand.action == "CancelReservation"
            )
        )
        command.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
    await worker.cycle()
    async with factory() as db:
        assert (await db.get(Reservation, result.id)).status == "cancel_pending"


async def test_restart_lease_expires_to_uncertain_without_new_reserve(
    reservation_fleet,
):
    factory, _, _, _, _, _, conn, _ = reservation_fleet
    result = await book(reservation_fleet)
    claimed = await worker.claim(result.id)
    assert claimed is not None
    async with factory() as db, db.begin():
        (await db.get(ReservationCommand, result.id)).locked_until = datetime.now(
            UTC
        ) - timedelta(seconds=1)
    await worker.reconcile(result.id)
    reply(conn)
    await worker.cycle()
    conn.call.assert_not_awaited()
    async with factory() as db:
        assert (await db.get(Reservation, result.id)).status == "uncertain"


async def test_verified_consume_replay_wrong_identity_and_wallet_recheck(
    reservation_fleet,
):
    factory, _, _, _connector, driver, _other, conn, _ = reservation_fleet
    result = await book(reservation_fleet)
    reply(conn)
    await worker.cycle()
    async with factory() as db, db.begin():
        tag = await db.get(DriverVirtualTag, driver.id)
        payload = {
            "connectorId": 1,
            "idTag": tag.id_tag,
            "reservationId": result.ocpp_id,
            "meterStart": 1000,
            "timestamp": datetime.now(UTC).isoformat(),
        }
        assert (
            await call(
                db,
                conn,
                "StartTransaction",
                {**payload, "reservationId": result.ocpp_id + 1},
            )
        ).payload["transactionId"] == 0
        assert (
            await call(db, conn, "StartTransaction", {**payload, "idTag": "WRONG-TAG"})
        ).payload["transactionId"] == 0
        wallet = await db.scalar(select(Wallet).where(Wallet.driver_id == driver.id))
        wallet.balance_vnd = 0
        await db.flush()
        assert (await call(db, conn, "StartTransaction", payload)).payload[
            "transactionId"
        ] == 0
        assert (await db.get(Reservation, result.id)).status == "active"
        wallet.balance_vnd = 1_000_000
        await db.flush()
        key = str(uuid4())
        first = await call(db, conn, "StartTransaction", payload, key)
        replay = await call(db, conn, "StartTransaction", payload, key)
        assert first.payload == replay.payload
        stored = await db.get(Reservation, result.id)
        charging = await db.get(ChargingSession, stored.session_id)
        assert (
            stored.status == "consumed"
            and stored.session_id == first.payload["transactionId"]
        )
        assert "reservation_not_verified" not in charging.review_reasons
        assert charging.driver_id == driver.id
    assert (
        await request("POST", f"/{result.id}/cancel", {"request_id": str(uuid4())})
    ).status_code == 409


async def test_suspend_enqueues_release_and_waives_future_no_show(reservation_fleet):
    factory, station, _, _, _, _, conn, _ = reservation_fleet
    result = await book(reservation_fleet)
    reply(conn)
    await worker.cycle()
    async with factory() as db, db.begin():
        (await db.get(Station, station.id)).status = "suspended"
    await worker.cycle()
    async with factory() as db:
        stored = await db.get(Reservation, result.id)
        assert stored.status == "cancelled" and stored.no_show_exempt


async def test_capability_probe_uses_trusted_response_and_invalidates_on_reboot(
    reservation_fleet,
):
    factory, _, point, connector, _, _, conn, _ = reservation_fleet
    async with factory() as db, db.begin():
        cap = await db.get(ReservationCapability, point.id)
        cap.checked_at, cap.supported = None, False
    assert (
        await request("POST", "/capabilities", {"connector_id": str(connector.id)})
    ).status_code == 202
    reply(conn)
    await worker.cycle()
    async with factory() as db, db.begin():
        cap = await db.get(ReservationCapability, point.id)
        assert cap.supported and cap.checked_at is not None
        (await db.get(ChargePoint, point.id)).last_boot_at = datetime.now(UTC)
    with pytest.raises(HTTPException) as error:
        await book(reservation_fleet)
    assert error.value.detail == "reservation_capability_unverified"


def race_process(url, connector_id, driver_ids, barrier, queue):
    async def run():
        engine = create_async_engine(url)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        barrier.wait(timeout=30)

        async def attempt(index):
            async with factory() as db:
                try:
                    async with db.begin():
                        await create_reservation(
                            db,
                            UUID(driver_ids[index % 2]),
                            uuid4(),
                            UUID(connector_id),
                            None,
                            EVIDENCE,
                        )
                    return "won"
                except HTTPException as error:
                    return error.detail

        results = await asyncio.gather(*(attempt(index) for index in range(10)))
        queue.put(results)
        await engine.dispose()

    asyncio.run(run())


async def test_twenty_requests_two_processes_one_hold_outbox_and_wire(
    reservation_fleet,
):
    factory, _, _, connector, driver, other, conn, _ = reservation_fleet
    url = factory.kw["bind"].url.render_as_string(hide_password=False)
    context = multiprocessing.get_context("spawn")
    barrier, queue = context.Barrier(3), context.Queue()
    processes = [
        context.Process(
            target=race_process,
            args=(
                url,
                str(connector.id),
                [str(driver.id), str(other.id)],
                barrier,
                queue,
            ),
        )
        for _ in range(2)
    ]
    try:
        for process in processes:
            process.start()
        await asyncio.to_thread(barrier.wait, timeout=30)
        results = []
        for _ in processes:
            results.extend(await asyncio.to_thread(queue.get, timeout=30))
        for process in processes:
            await asyncio.to_thread(process.join, timeout=10)
            assert process.exitcode == 0
        assert results.count("won") == 1
        assert results.count("connector_reserved") == 19
        async with factory() as db:
            assert await db.scalar(select(func.count()).select_from(Reservation)) == 1
            assert (
                await db.scalar(select(func.count()).select_from(ReservationCommand))
                == 1
            )
        reply(conn)
        await worker.cycle()
        assert conn.call.await_count == 1
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)
        queue.close()


async def test_migration_roundtrip_and_positive_sequence(reservation_fleet):
    factory, station, point, *_ = reservation_fleet
    url = factory.kw["bind"].url.render_as_string(hide_password=False)
    for command in (["downgrade", "c230023a2026"], ["upgrade", "head"]):
        result = await asyncio.to_thread(
            subprocess.run,
            [sys.executable, "-m", "alembic", *command],
            env=os.environ | {"DATABASE_URL": url},
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
    async with factory() as db, db.begin():
        db.add(
            ReservationCapability(
                charge_point_id=point.id,
                boot_at=point.last_boot_at,
                supported=True,
                checked_at=datetime.now(UTC),
                outcome="supported",
            )
        )
    assert (await book(reservation_fleet)).ocpp_id > 0
    async with factory() as db:
        assert (await db.get(Station, station.id)).name == station.name


async def test_expiry_requires_fresh_source_available_and_rejects_late_cancel(
    reservation_fleet,
):
    factory, _, point, connector, _, _, conn, _ = reservation_fleet
    result = await book(reservation_fleet)
    reply(conn)
    await worker.cycle()
    now = datetime.now(UTC)
    async with factory() as db, db.begin():
        row = await db.get(Reservation, result.id)
        row.created_at = row.arrival_at = now - timedelta(minutes=20)
        row.expires_at = now - timedelta(seconds=40)
        cp = await db.get(ChargePoint, point.id)
        cp.last_boot_at = now - timedelta(hours=1)
        cp.last_seen_at = now
        plug = await db.get(Connector, connector.id)
        plug.status = plug.raw_ocpp_status = "Available"
        plug.last_status_notification_at = plug.status_updated_at = now - timedelta(
            minutes=1
        )
    response = await request(
        "POST", f"/{result.id}/cancel", {"request_id": str(uuid4())}
    )
    assert (
        response.status_code == 409
        and response.json()["detail"] == "reservation_expired"
    )
    await worker.reconcile(result.id)
    async with factory() as db, db.begin():
        assert (await db.get(Reservation, result.id)).status == "expiry_release_pending"
        plug = await db.get(Connector, connector.id)
        plug.last_status_notification_at = plug.status_updated_at = now
    await worker.reconcile(result.id)
    async with factory() as db:
        stored = await db.get(Reservation, result.id)
        assert stored.status == "expired" and not stored.no_show_exempt


@pytest.mark.parametrize("hours", [-1, 3])
async def test_arrival_window_rejected_without_outbox(reservation_fleet, hours):
    factory, _, _, connector, *_ = reservation_fleet
    response = await request(
        "POST",
        body={
            "request_id": str(uuid4()),
            "connector_id": str(connector.id),
            "arrival_at": (datetime.now(UTC) + timedelta(hours=hours)).isoformat(),
        },
    )
    assert response.status_code == 422
    async with factory() as db:
        assert (
            await db.scalar(select(func.count()).select_from(ReservationCommand)) == 0
        )


async def test_real_tcp_reserve_raw_status_consume_and_cancel(
    reservation_fleet, monkeypatch
):
    import uvicorn
    from websockets.asyncio.client import connect

    from src.modules.billing import closure
    from src.modules.billing.models import Invoice
    from src.modules.ocpp import dispatcher, service, transport
    from src.modules.wallet.models import WalletLedger

    factory, _, point, connector, driver, *_ = reservation_fleet
    for module in (service, transport, dispatcher):
        monkeypatch.setattr(module, "SessionFactory", factory)
    monkeypatch.setattr(closure, "SessionFactory", factory)
    runner = closure.ClosureRunner(settle=True)
    monkeypatch.setattr(closure, "_runner", runner)
    closing = asyncio.create_task(runner.worker())
    monkeypatch.setattr(OcppConnection, "call", REAL_CALL)
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    server = uvicorn.Server(
        uvicorn.Config(app, lifespan="off", log_level="error", ws="websockets-sansio")
    )
    serving = asyncio.create_task(server.serve(sockets=[listener]))
    try:
        async with asyncio.timeout(10):
            while not server.started:
                if serving.done():
                    await serving
                await asyncio.sleep(0.01)
        async with connect(
            f"ws://127.0.0.1:{listener.getsockname()[1]}/ocpp/{point.code}",
            subprotocols=["ocpp1.6"],
        ) as ws:

            async def wire(action, payload):
                key = str(uuid4())
                await ws.send(json.dumps([2, key, action, payload]))
                response = json.loads(await asyncio.wait_for(ws.recv(), 5))
                assert response[:2] == [3, key], response
                return response[2]

            assert (
                await wire(
                    "BootNotification",
                    {"chargePointVendor": "G5", "chargePointModel": "Reservation"},
                )
            )["status"] == "Accepted"
            async with factory() as db, db.begin():
                cap = await db.get(ReservationCapability, point.id)
                cap.checked_at = None
                cap.next_attempt_at = datetime.now(UTC)
            cycle = asyncio.create_task(worker.cycle())
            probe = json.loads(await asyncio.wait_for(ws.recv(), 5))
            assert probe[2] == "GetConfiguration"
            await ws.send(
                json.dumps(
                    [
                        3,
                        probe[1],
                        {
                            "configurationKey": [
                                {
                                    "key": "SupportedFeatureProfiles",
                                    "readonly": True,
                                    "value": "Core,Reservation",
                                }
                            ]
                        },
                    ]
                )
            )
            await cycle
            booked = await book(reservation_fleet)
            cycle = asyncio.create_task(worker.cycle())
            command = json.loads(await asyncio.wait_for(ws.recv(), 5))
            assert (
                command[2] == "ReserveNow"
                and command[3]["reservationId"] == booked.ocpp_id
            )
            assert command[3]["connectorId"] == 1
            await ws.send(json.dumps([3, command[1], {"status": "Accepted"}]))
            await cycle
            await wire(
                "StatusNotification",
                {
                    "connectorId": 1,
                    "errorCode": "NoError",
                    "status": "Reserved",
                    "timestamp": datetime.now(UTC).isoformat(),
                },
            )
            async with factory() as db:
                assert (
                    await db.get(Connector, connector.id)
                ).raw_ocpp_status == "Reserved"
                assert (await db.get(Reservation, booked.id)).status == "active"
            cancelled = await request(
                "POST", f"/{booked.id}/cancel", {"request_id": str(uuid4())}
            )
            assert cancelled.json()["status"] == "cancel_pending"
            cycle = asyncio.create_task(worker.cycle())
            command = json.loads(await asyncio.wait_for(ws.recv(), 5))
            assert command[2] == "CancelReservation" and command[3] == {
                "reservationId": booked.ocpp_id
            }
            await ws.send(json.dumps([3, command[1], {"status": "Accepted"}]))
            await cycle
            async with factory() as db:
                assert (await db.get(Reservation, booked.id)).status == "cancelled"
                assert (
                    await db.get(Connector, connector.id)
                ).raw_ocpp_status == "Reserved"
            await wire(
                "StatusNotification",
                {
                    "connectorId": 1,
                    "errorCode": "NoError",
                    "status": "Available",
                    "timestamp": datetime.now(UTC).isoformat(),
                },
            )
            booked = await book(reservation_fleet)
            cycle = asyncio.create_task(worker.cycle())
            command = json.loads(await asyncio.wait_for(ws.recv(), 5))
            await ws.send(json.dumps([3, command[1], {"status": "Accepted"}]))
            await cycle
            started = await wire(
                "StartTransaction",
                {
                    "connectorId": 1,
                    "reservationId": booked.ocpp_id,
                    "idTag": command[3]["idTag"],
                    "meterStart": 1000,
                    "timestamp": datetime.now(UTC).isoformat(),
                },
            )
            assert (
                started["transactionId"] > 0
                and started["idTagInfo"]["status"] == "Accepted"
            )
            async with factory() as db:
                row = await db.get(Reservation, booked.id)
                session = await db.get(ChargingSession, row.session_id)
                assert row.status == "consumed" and session.driver_id == driver.id
                assert "reservation_not_verified" not in session.review_reasons
            await wire(
                "StopTransaction",
                {
                    "transactionId": started["transactionId"],
                    "meterStop": 2000,
                    "timestamp": datetime.now(UTC).isoformat(),
                    "reason": "EVDisconnected",
                },
            )
            async with asyncio.timeout(10):
                while True:
                    async with factory() as db:
                        session = await db.get(
                            ChargingSession, started["transactionId"]
                        )
                        if session.settlement_completed_at is not None:
                            invoice = await db.scalar(
                                select(Invoice).where(Invoice.session_id == session.id)
                            )
                            wallet = await db.scalar(
                                select(Wallet).where(Wallet.driver_id == driver.id)
                            )
                            assert invoice.total_vnd == 2500
                            assert wallet.balance_vnd == 1_000_000 - 2500
                            assert (
                                await db.scalar(
                                    select(func.count())
                                    .select_from(WalletLedger)
                                    .where(WalletLedger.reference_id == str(session.id))
                                )
                                == 1
                            )
                            assert session.connector_released_at is not None
                            break
                    await asyncio.sleep(0.01)
    finally:
        server.should_exit = True
        await asyncio.wait_for(serving, 10)
        listener.close()
        closing.cancel()
        await asyncio.gather(closing, return_exceptions=True)
