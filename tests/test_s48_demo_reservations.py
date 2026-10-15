"""Verify the shipped simulator against the actual CSMS socket and API."""

# ruff: noqa: F401, F811 -- imported pytest fixture dependencies
import asyncio
import socket
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import uvicorn

from scripts.ocpp_control_simulator import ConnectorState, run
from src.entrypoints.http import app
from src.modules.charging import driver as driver_service
from src.modules.charging.models import ChargingSession
from src.modules.ocpp import dispatcher, service, transport
from src.modules.ocpp.connection_registry import OcppConnection
from src.modules.reservations.models import Reservation, ReservationCapability
from tests.test_g5_reservations import (
    REAL_CALL,
    api_db,
    committed_tariff_db,
    fleet,
    request,
    reservation_fleet,
    worker,
)


async def test_shipped_simulator_probe_book_cancel_and_consume(
    reservation_fleet, monkeypatch, tmp_path
):
    factory, _, point, connector, driver, *_ = reservation_fleet
    for module in (service, transport, dispatcher, driver_service):
        monkeypatch.setattr(module, "SessionFactory", factory)
    monkeypatch.setattr(OcppConnection, "call", REAL_CALL)
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(app, lifespan="off", log_level="error", ws="websockets-sansio")
    )
    serving = asyncio.create_task(server.serve(sockets=[listener]))
    simulator = None
    stop = asyncio.Event()
    states = {1: ConnectorState()}
    try:
        async with asyncio.timeout(10):
            while not server.started:
                await asyncio.sleep(0.01)
        simulator = asyncio.create_task(
            run(
                f"ws://127.0.0.1:{port}",
                point.code,
                None,
                "Accepted",
                False,
                connectors=states,
                start_delay=0,
                stop_event=stop,
                profile_store=tmp_path / "state.json",
            )
        )
        async with asyncio.timeout(10):
            while True:
                async with factory() as db:
                    observed = await db.get(type(point), point.id)
                    if observed.last_boot_at != point.last_boot_at:
                        break
                await asyncio.sleep(0.02)
        probe = await request(
            "POST", "/capabilities", {"connector_id": str(connector.id)}
        )
        assert probe.status_code == 202
        await worker.cycle()
        async with factory() as db:
            cap = await db.get(ReservationCapability, point.id)
            assert cap.supported and cap.outcome == "supported"

        async def book():
            response = await request(
                "POST",
                "",
                {
                    "request_id": str(uuid4()),
                    "connector_id": str(connector.id),
                    "arrival_at": None,
                },
            )
            assert response.status_code == 202, response.text
            await worker.cycle()
            async with factory() as db:
                row = await db.get(Reservation, response.json()["id"])
                assert row.status == "active"
                return row

        row = await book()
        assert not states[1].reserve_start("OTHER-DRIVER")
        assert (
            states[1].status == "Reserved" and states[1].reservation_id == row.ocpp_id
        )
        cancelled = await request(
            "POST", f"/{row.id}/cancel", {"request_id": str(uuid4())}
        )
        assert cancelled.status_code == 202
        await worker.cycle()
        async with asyncio.timeout(5):
            while True:
                async with factory() as db:
                    observed = await db.get(type(connector), connector.id)
                    if observed.status == "Available":
                        break
                await asyncio.sleep(0.02)
        row = await book()
        result = await driver_service.remote_start(driver.id, uuid4(), connector.id)
        assert result["status"] in {"Accepted", "Started"}
        async with asyncio.timeout(8):
            while True:
                async with factory() as db:
                    booked = await db.get(Reservation, row.id)
                    if booked.status == "consumed" and states[1].reservation_id is None:
                        session = await db.get(ChargingSession, booked.session_id)
                        assert session.driver_id == driver.id
                        assert states[1].reservation_id is None
                        break
                await asyncio.sleep(0.02)
    finally:
        stop.set()
        if simulator is not None:
            await asyncio.wait_for(simulator, 10)
        server.should_exit = True
        await asyncio.wait_for(serving, 10)


async def test_explicit_probe_retries_cached_unsupported(reservation_fleet):
    factory, _, point, connector, *_ = reservation_fleet
    async with factory() as db, db.begin():
        cap = await db.get(ReservationCapability, point.id)
        cap.supported = False
        cap.outcome = "unsupported"
    response = await request(
        "POST", "/capabilities", {"connector_id": str(connector.id)}
    )
    assert response.status_code == 202
    async with factory() as db:
        cap = await db.get(ReservationCapability, point.id)
        assert cap.checked_at is None and cap.outcome == "queued"


def test_simulator_releases_expired_hold_and_keeps_live_hold_private():
    state = ConnectorState(
        status="Reserved",
        reservation_id=42,
        reservation_tag="OWNER",
        reservation_expires_at=datetime.now(UTC) + timedelta(minutes=1),
    )
    assert not state.reserve_start("OTHER")
    assert state.reservation_id == 42 and state.status == "Reserved"
    state.reservation_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    assert state.expire_reservation()
    assert state.status == "Available"
    assert state.reservation_id is None and state.reservation_tag is None
