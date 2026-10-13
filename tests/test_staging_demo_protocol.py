import asyncio
import json
from unittest.mock import AsyncMock
from uuid import uuid4

from websockets.asyncio.server import serve

from scripts import ocpp_control_simulator, staging_demo
from scripts.ocpp_control_simulator import ConnectorState


async def test_remote_stop_waits_for_separate_simulated_unplug(tmp_path, monkeypatch):
    """Local sockets only: no staging API, database, accounts or financial writes."""
    monkeypatch.setattr(staging_demo, "STOP", tmp_path / "stop.request")
    monkeypatch.setattr(
        ocpp_control_simulator,
        "load_connectors",
        AsyncMock(return_value={1: ConnectorState()}),
    )

    class Database:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def execute(self, *args):
            return self

        def all(self):
            return []

    monkeypatch.setattr(staging_demo, "SessionFactory", Database)
    ready = asyncio.Event()
    socket_ready = asyncio.Future()
    requests = {}
    notices = []
    stopped = []
    transaction = 76

    async def handler(socket):
        nonlocal transaction
        socket_ready.set_result(socket)
        async for raw in socket:
            frame = json.loads(raw)
            if frame[0] == 3:
                requests.pop(frame[1]).set_result(frame[2])
                continue
            _, key, action, body = frame
            response = {}
            if action == "BootNotification":
                assert len(body["chargePointVendor"]) <= 20
                response = {"status": "Accepted"}
            elif action == "StatusNotification":
                assert body["timestamp"]
                notices.append(body["status"])
                ready.set()
            elif action == "StartTransaction":
                transaction += 1
                response = {
                    "transactionId": transaction,
                    "idTagInfo": {"status": "Accepted"},
                }
            elif action == "StopTransaction":
                stopped.append(body)
            await socket.send(json.dumps([3, key, response]))

    async def command(action, payload):
        key = str(uuid4())
        future = asyncio.get_running_loop().create_future()
        requests[key] = future
        await (await socket_ready).send(json.dumps([2, key, action, payload]))
        return await asyncio.wait_for(future, 5)

    async def until(predicate):
        async with asyncio.timeout(5):
            while not predicate():
                await asyncio.sleep(0.01)

    async with serve(handler, "127.0.0.1", 0) as server:
        monkeypatch.setattr(
            staging_demo, "OCPP", f"ws://127.0.0.1:{server.sockets[0].getsockname()[1]}"
        )
        charger = staging_demo.Charger(
            {"code": "DEMO-STG-TD-001", "fault_connector": None}
        )
        task = asyncio.create_task(charger.run())
        try:
            await asyncio.wait_for(ready.wait(), 5)
            await until(lambda: charger.online)
            assert (
                await command(
                    "RemoteStartTransaction", {"connectorId": 1, "idTag": "TEST"}
                )
            )["status"] == "Accepted"
            await until(lambda: "Charging" in notices)
            notices.clear()
            assert (await command("RemoteStopTransaction", {"transactionId": 77}))[
                "status"
            ] == "Accepted"
            await until(lambda: "Finishing" in notices)
            assert stopped[0]["reason"] == "Remote" and "Available" not in notices
            unplug = {
                "vendorId": "CSMS-DEMO",
                "messageId": "Unplug",
                "data": json.dumps({"transactionId": 77, "connectorId": 1}),
            }
            assert (await command("DataTransfer", unplug))["status"] == "Accepted"
            await until(lambda: "Available" in notices)
            assert len(stopped) == 1
            await until(lambda: not charger.awaiting_unplug)
            assert (await command("DataTransfer", unplug))["status"] == "Rejected"
            notices.clear()
            await command("RemoteStartTransaction", {"connectorId": 1, "idTag": "TEST"})
            await until(lambda: "Charging" in notices)
            unplug["data"] = json.dumps({"transactionId": 78, "connectorId": 1})
            assert (await command("DataTransfer", unplug))["status"] == "Accepted"
            await until(lambda: len(stopped) == 2)
            assert stopped[1]["reason"] == "EVDisconnected"
        finally:
            staging_demo.STOP.touch()
            await asyncio.wait_for(task, 12)
