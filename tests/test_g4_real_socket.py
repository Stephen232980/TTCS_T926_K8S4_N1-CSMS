"""S-66 suspend/resume and normal settlement on an already connected socket."""

import asyncio
import json
import socket
import sys
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import uvicorn
from websockets.asyncio.client import connect

from src.entrypoints.http import app
from src.modules.billing.closure import chot_phien
from src.modules.charging.models import ChargingSession
from src.platform.database.session import SessionFactory
from tests.test_flat_tariff_api import api_db, committed_tariff_db  # noqa: F401
from tests.test_g4_station_operation_discovery import fleet as operation_fleet
from tests.test_g4_station_operation_discovery import operate

fleet = operation_fleet


async def test_suspend_resume_real_socket_and_settle_existing_session(
    fleet, monkeypatch
):
    factory, station, point, _, _, _, tag, _ = fleet
    for name, module in tuple(sys.modules.items()):
        if (
            name.startswith("src.")
            and getattr(module, "SessionFactory", None) is SessionFactory
        ):
            monkeypatch.setattr(module, "SessionFactory", factory)
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(app, log_level="error", ws="websockets-sansio", lifespan="off")
    )
    serving = asyncio.create_task(server.serve(sockets=[listener]))

    async def request(ws, action, payload):
        uid = str(uuid4())
        await ws.send(json.dumps([2, uid, action, payload]))
        async with asyncio.timeout(5):
            reply = json.loads(await ws.recv())
        assert reply[:2] == [3, uid], reply
        return reply[2]

    try:
        async with asyncio.timeout(10):
            while not server.started:
                if serving.done():
                    await serving
                await asyncio.sleep(0.01)
        async with connect(
            f"ws://127.0.0.1:{port}/ocpp/{point.code}", subprotocols=["ocpp1.6"]
        ) as ws:
            assert (
                await request(
                    ws,
                    "BootNotification",
                    {"chargePointVendor": "G4", "chargePointModel": "LocalTest"},
                )
            )["status"] == "Accepted"
            stamp = datetime.now(UTC)
            start_payload = {
                "connectorId": 1,
                "idTag": tag,
                "meterStart": 1000,
                "timestamp": stamp.isoformat(),
            }
            accepted = await request(ws, "StartTransaction", start_payload)
            assert accepted["idTagInfo"]["status"] == "Accepted"
            session_id = accepted["transactionId"]
            assert (await operate(station, "suspended")).status_code == 200
            assert (await request(ws, "Authorize", {"idTag": tag}))["idTagInfo"][
                "status"
            ] == "Blocked"
            assert (
                await request(
                    ws,
                    "StartTransaction",
                    {
                        **start_payload,
                        "timestamp": (stamp + timedelta(seconds=1)).isoformat(),
                    },
                )
            )["transactionId"] == 0
            assert (
                await request(
                    ws,
                    "MeterValues",
                    {
                        "connectorId": 1,
                        "transactionId": session_id,
                        "meterValue": [
                            {
                                "timestamp": (stamp + timedelta(seconds=2)).isoformat(),
                                "sampledValue": [{"value": "2000"}],
                            }
                        ],
                    },
                )
                == {}
            )
            assert (
                await request(
                    ws,
                    "StopTransaction",
                    {
                        "transactionId": session_id,
                        "meterStop": 2000,
                        "timestamp": (stamp + timedelta(seconds=3)).isoformat(),
                        "reason": "EVDisconnected",
                    },
                )
                == {}
            )
            async with factory() as db, db.begin():
                result = await chot_phien(session_id, db=db, settle=True)
                assert result.status == "ready", result
                charging = await db.get(ChargingSession, session_id)
                assert charging.connector_released_at is not None
                assert charging.settlement_reason == "debited"
                assert result.invoice.total_vnd == 2500
            assert (await operate(station, "active", version=2)).status_code == 200
            assert (await request(ws, "Authorize", {"idTag": tag}))["idTagInfo"][
                "status"
            ] == "Accepted"
    finally:
        server.should_exit = True
        await asyncio.wait_for(serving, 10)
        listener.close()
