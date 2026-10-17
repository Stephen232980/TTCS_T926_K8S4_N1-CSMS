"""T-106 threshold and funded retry through a real OCPP WebSocket."""

import asyncio
import json
import socket
import sys
from datetime import UTC, datetime
from uuid import uuid4

import httpx
import pytest
import uvicorn
from sqlalchemy import func, select
from websockets.asyncio.client import connect

from simulator.client import _call
from simulator.t108_contract import new_manifest
from simulator.t108_fixture import prepare_station, user
from src.entrypoints.http import app
from src.modules.charging.driver_provisioning import ensure_driver_resources
from src.modules.charging.models import ChargingSession
from src.modules.identity.authorization import AuthorizationEvidence, CurrentActor
from src.modules.identity.dependencies import get_current_actor
from src.modules.wallet.manual_topup import ManualTopupRequest, nap_tay
from src.modules.wallet.models import Wallet, WalletLedger
from src.platform.database.session import SessionFactory
from tests.test_effective_tariffs import committed_tariff_db as isolated_ocpp_db

committed_tariff_db = isolated_ocpp_db


@pytest.mark.asyncio
async def test_thresholds_and_real_topup_retry(committed_tariff_db, monkeypatch):
    factory = committed_tariff_db
    for name, module in tuple(sys.modules.items()):
        if (
            name.startswith("src.")
            and getattr(module, "SessionFactory", None) is SessionFactory
        ):
            monkeypatch.setattr(module, "SessionFactory", factory)
    manifest = new_manifest(
        revision="t106-test", mode="ci", count=3, duration=120, boundary=60
    )
    admin_id = uuid4()
    tags = []
    async with factory() as db, db.begin():
        await prepare_station(db, manifest)
        await user(db, admin_id, f"t106-admin-{admin_id}@example.com", ["admin"])
        for participant, balance in zip(manifest.participants, (14999, 15000, 15001)):
            driver = await user(
                db, participant.driver_id, participant.driver_email, ["driver"]
            )
            tags.append((await ensure_driver_resources(db, driver)).id_tag)
            await nap_tay(
                db,
                driver_id=driver.id,
                actor_id=admin_id,
                request=ManualTopupRequest(
                    reason="QA seed funding",
                    amount_vnd=balance,
                    receipt_code=f"t106-{driver.id}",
                ),
                authorization=AuthorizationEvidence(
                    permission="admin.wallet.manual_topup", roles=("admin",)
                ),
            )
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(app, log_level="error", ws="websockets-sansio")
    )
    serving = asyncio.create_task(server.serve(sockets=[listener]))
    try:
        async with asyncio.timeout(10):
            while not server.started:
                await asyncio.sleep(0.05)
        for index, participant in enumerate(manifest.participants):
            driver_id = participant.driver_id
            app.dependency_overrides[get_current_actor] = lambda driver_id=driver_id: (
                CurrentActor(driver_id, frozenset({"driver"}))
            )
            async with connect(
                f"ws://127.0.0.1:{port}/ocpp/{participant.charge_point_code}",
                subprotocols=["ocpp1.6"],
            ) as ws:
                assert (
                    await _call(
                        ws,
                        "BootNotification",
                        {"chargePointVendor": "T106", "chargePointModel": "Acceptance"},
                    )
                )["status"] == "Accepted"
                await _call(
                    ws,
                    "StatusNotification",
                    {"connectorId": 1, "errorCode": "NoError", "status": "Available"},
                )
                expected = "Blocked" if index == 0 else "Accepted"
                assert (await _call(ws, "Authorize", {"idTag": tags[index]}))[
                    "idTagInfo"
                ]["status"] == expected
                payload = {
                    "connectorId": 1,
                    "idTag": tags[index],
                    "meterStart": 1000,
                    "timestamp": datetime.now(UTC).isoformat(),
                }
                if index == 0:
                    async with httpx.AsyncClient(
                        transport=httpx.ASGITransport(app=app), base_url="http://test"
                    ) as client:
                        denied = await client.post(
                            "/api/v1/driver/charging/start",
                            json={
                                "request_id": str(uuid4()),
                                "connector_id": str(participant.connector_id),
                            },
                        )
                        assert denied.status_code == 409
                        assert denied.json()["detail"] == {
                            "reason": "wallet_low",
                            "balance_vnd": 14999,
                            "minimum_balance_vnd": 15000,
                        }
                    assert (await _call(ws, "StartTransaction", payload))[
                        "transactionId"
                    ] == 0
                    async with factory() as db, db.begin():
                        assert (
                            await db.scalar(
                                select(func.count())
                                .select_from(ChargingSession)
                                .where(ChargingSession.driver_id == driver_id)
                            )
                            == 0
                        )
                        await nap_tay(
                            db,
                            driver_id=driver_id,
                            actor_id=admin_id,
                            request=ManualTopupRequest(
                                reason="QA seed funding",
                                amount_vnd=1,
                                receipt_code=f"t106-retry-{driver_id}",
                            ),
                            authorization=AuthorizationEvidence(
                                permission="admin.wallet.manual_topup", roles=("admin",)
                            ),
                        )
                    async with httpx.AsyncClient(
                        transport=httpx.ASGITransport(app=app), base_url="http://test"
                    ) as client:
                        posted = asyncio.create_task(
                            client.post(
                                "/api/v1/driver/charging/start",
                                json={
                                    "request_id": str(uuid4()),
                                    "connector_id": str(participant.connector_id),
                                },
                            )
                        )
                        command = json.loads(await asyncio.wait_for(ws.recv(), 5))
                        assert command[2] == "RemoteStartTransaction"
                        await ws.send(
                            json.dumps([3, command[1], {"status": "Accepted"}])
                        )
                        assert (await posted).json()["status"] == "Accepted"
                    assert (await _call(ws, "Authorize", {"idTag": tags[index]}))[
                        "idTagInfo"
                    ]["status"] == "Accepted"
                begun = await _call(ws, "StartTransaction", payload)
                assert (
                    begun["idTagInfo"]["status"] == "Accepted"
                    and begun["transactionId"] > 0
                )
                async with factory() as db:
                    assert (
                        await db.scalar(
                            select(func.count())
                            .select_from(ChargingSession)
                            .where(ChargingSession.driver_id == driver_id)
                        )
                        == 1
                    )
                    if index == 0:
                        wallet = await db.scalar(
                            select(Wallet).where(Wallet.driver_id == driver_id)
                        )
                        total = await db.scalar(
                            select(func.sum(WalletLedger.amount_vnd)).where(
                                WalletLedger.wallet_id == wallet.id
                            )
                        )
                        assert wallet.balance_vnd == total == 15000
    finally:
        app.dependency_overrides.pop(get_current_actor, None)
        server.should_exit = True
        await asyncio.wait_for(serving, 10)
        listener.close()
