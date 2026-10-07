"""S-19 AC4: 20 real OCPP sockets, three synchronized 10-second reports."""

import asyncio
import json
import socket
from contextlib import AsyncExitStack
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from time import perf_counter
from uuid import uuid4

import pytest
import uvicorn
from sqlalchemy import delete, func, select
from websockets.asyncio.client import connect

from src.entrypoints.http import app
from src.modules.charging.models import ChargingSession, MeterSample
from src.modules.identity.models import User
from src.modules.stations.models import ChargePoint, Connector, Station
from src.platform.database.session import SessionFactory
from tests.test_ocpp_foundation import charger_fixture


@pytest.mark.asyncio
async def test_twenty_real_sockets_periodic_meter_replies_under_200ms():
    async with SessionFactory() as session, session.begin():
        station, first = await charger_fixture(session)
        station_id, owner_id = station.id, station.owner_id
        chargers = [first] + [
            ChargePoint(station_id=station_id, code=f"s19-{uuid4()}") for _ in range(19)
        ]
        session.add_all(chargers)
        await session.flush()
        connectors = [
            Connector(charge_point_id=cp.id, connector_number=1) for cp in chargers
        ]
        session.add_all(connectors)
        await session.flush()
        transactions = [
            ChargingSession(
                charge_point_id=cp.id,
                connector_id=connector.id,
                tag_tail="TEST",
                authorization_status="Invalid",
                started_at=datetime.now(UTC) - timedelta(seconds=30),
                meter_start_wh=Decimal(1000),
                review_reasons=[],
            )
            for cp, connector in zip(chargers, connectors)
        ]
        session.add_all(transactions)
        await session.flush()
        codes = [cp.code for cp in chargers]
        charger_ids = [cp.id for cp in chargers]
        transaction_ids = [tx.id for tx in transactions]

    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    server = uvicorn.Server(
        uvicorn.Config(app, log_level="error", ws="websockets-sansio")
    )
    serving = asyncio.create_task(server.serve(sockets=[listener]))

    async def call(ws, action, payload, message_id=None):
        uid = message_id or str(uuid4())
        raw = json.dumps([2, uid, action, payload])
        started = perf_counter()
        await ws.send(raw)
        async with asyncio.timeout(5):
            reply = json.loads(await ws.recv())
        elapsed = perf_counter() - started
        assert reply[:2] == [3, uid], reply
        return elapsed, reply

    try:
        async with asyncio.timeout(10):
            while not server.started:
                if serving.done():
                    await serving
                    raise RuntimeError("Benchmark server did not start")
                await asyncio.sleep(0.01)
        port = listener.getsockname()[1]
        async with AsyncExitStack() as stack:
            sockets = [
                await stack.enter_async_context(
                    connect(
                        f"ws://127.0.0.1:{port}/ocpp/{code}",
                        subprotocols=["ocpp1.6"],
                    )
                )
                for code in codes
            ]
            boots = await asyncio.gather(
                *(
                    call(
                        ws,
                        "BootNotification",
                        {"chargePointVendor": "S19", "chargePointModel": "Benchmark"},
                    )
                    for ws in sockets
                )
            )
            assert all(reply[2]["status"] == "Accepted" for _, reply in boots)
            await asyncio.gather(*(call(ws, "Heartbeat", {}) for ws in sockets))
            cadence_start = perf_counter()
            for cycle in range(3):
                await asyncio.sleep(max(0, cadence_start + cycle * 10 - perf_counter()))
                payloads = [
                    {
                        "connectorId": 1,
                        "transactionId": tid,
                        "meterValue": [
                            {
                                "timestamp": datetime.now(UTC).isoformat(),
                                "sampledValue": [
                                    {"value": str(2000 + cycle * 100)},
                                    {
                                        "measurand": "Power.Active.Import",
                                        "value": "7200",
                                    },
                                    {"measurand": "Voltage", "value": "230"},
                                    {"measurand": "Current.Import", "value": "32"},
                                ],
                            }
                        ],
                    }
                    for tid in transaction_ids
                ]
                message_ids = [str(uuid4()) for _ in sockets]
                replies = await asyncio.gather(
                    *(
                        call(ws, "MeterValues", payload, uid)
                        for ws, payload, uid in zip(sockets, payloads, message_ids)
                    )
                )
                slowest = max(elapsed for elapsed, _ in replies)
                print(
                    f"S-19 real sockets cycle {cycle + 1}: max={slowest * 1000:.1f}ms"
                )
                assert slowest < 0.2, f"Slowest meter response: {slowest:.3f}s"
                # Each acknowledgement must follow a durable commit, including all samples.
                async with SessionFactory() as session:
                    assert await session.scalar(
                        select(func.count())
                        .select_from(MeterSample)
                        .where(MeterSample.session_id.in_(transaction_ids))
                    ) == 20 * 4 * (cycle + 1)
                replayed = await asyncio.gather(
                    *(
                        call(ws, "MeterValues", payload, uid)
                        for ws, payload, uid in zip(sockets, payloads, message_ids)
                    )
                )
                assert [reply for _, reply in replayed] == [
                    reply for _, reply in replies
                ]
            async with SessionFactory() as session:
                assert (
                    await session.scalar(
                        select(func.count())
                        .select_from(MeterSample)
                        .where(MeterSample.session_id.in_(transaction_ids))
                    )
                    == 240
                )
    finally:
        server.should_exit = True
        try:
            await asyncio.wait_for(serving, timeout=10)
        finally:
            listener.close()
            async with SessionFactory() as session, session.begin():
                await session.execute(
                    delete(ChargingSession).where(
                        ChargingSession.id.in_(transaction_ids)
                    )
                )
                await session.execute(
                    delete(Connector).where(Connector.charge_point_id.in_(charger_ids))
                )
                await session.execute(
                    delete(ChargePoint).where(ChargePoint.id.in_(charger_ids))
                )
                await session.execute(delete(Station).where(Station.id == station_id))
                await session.execute(delete(User).where(User.id == owner_id))
