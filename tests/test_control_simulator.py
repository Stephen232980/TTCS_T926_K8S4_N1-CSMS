"""Exercise simulator multi-connector commands over an actual WebSocket."""

import asyncio
import json
from contextlib import suppress
from uuid import uuid4

from websockets.asyncio.server import serve

from scripts.ocpp_control_simulator import ConnectorState, run


async def test_control_simulator_routes_sessions_and_rejects_unready_connectors():
    commands = {}
    starts = {}
    meters = {}
    stopped = []
    ready = asyncio.Event()
    socket_ready = asyncio.Future()
    status_reports = set()

    async def handler(socket):
        socket_ready.set_result(socket)
        async for raw in socket:
            frame = json.loads(raw)
            if frame[0] == 3:
                commands.pop(frame[1]).set_result(frame[2])
                continue
            _, uid, action, payload = frame
            response = {}
            if action == "BootNotification":
                response = {"status": "Accepted", "interval": 60}
            elif action == "StatusNotification":
                status_reports.add(payload["connectorId"])
                if len(status_reports) == 4:
                    ready.set()
            elif action == "StartTransaction":
                number = payload["connectorId"]
                starts[number] = 100 + number
                response = {
                    "transactionId": starts[number],
                    "idTagInfo": {"status": "Accepted"},
                }
            elif action == "MeterValues":
                meters[payload["connectorId"]] = payload
            elif action == "StopTransaction":
                stopped.append(payload["transactionId"])
            await socket.send(json.dumps([3, uid, response]))

    async def command(action, payload):
        socket = await socket_ready
        uid = str(uuid4())
        future = asyncio.get_running_loop().create_future()
        commands[uid] = future
        await socket.send(json.dumps([2, uid, action, payload]))
        return await asyncio.wait_for(future, 5)

    async def until(predicate):
        async with asyncio.timeout(5):
            while not predicate():
                await asyncio.sleep(0.02)

    states = {n: ConnectorState() for n in range(1, 5)}
    states[4].status = "Faulted"
    stop = asyncio.Event()
    async with serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        task = asyncio.create_task(
            run(
                f"ws://127.0.0.1:{port}",
                "TEST",
                None,
                "Accepted",
                False,
                start_delay=0.1,
                connectors=states,
                stop_event=stop,
            )
        )
        try:
            await asyncio.wait_for(ready.wait(), 5)
            assert (
                await command(
                    "RemoteStartTransaction", {"connectorId": 2, "idTag": "A"}
                )
            )["status"] == "Accepted"
            assert (
                await command(
                    "RemoteStartTransaction", {"connectorId": 2, "idTag": "B"}
                )
            )["status"] == "Rejected"
            assert (
                await command(
                    "RemoteStartTransaction", {"connectorId": 3, "idTag": "B"}
                )
            )["status"] == "Accepted"
            for number in [4, 5]:
                assert (
                    await command(
                        "RemoteStartTransaction", {"connectorId": number, "idTag": "C"}
                    )
                )["status"] == "Rejected"
            await until(lambda: len(starts) == 2 and len(meters) == 2)
            assert meters[2]["transactionId"] == 102
            assert meters[3]["transactionId"] == 103
            assert int(meters[2]["meterValue"][0]["sampledValue"][0]["value"]) > 1000
            assert (await command("RemoteStopTransaction", {"transactionId": 102}))[
                "status"
            ] == "Accepted"
            await until(lambda: states[2].transaction_id is None)
            assert states[2].status == "Available"
            assert states[3].transaction_id == 103
            assert stopped == [102]
            assert (
                await command(
                    "RemoteStartTransaction", {"connectorId": 2, "idTag": "A"}
                )
            )["status"] == "Accepted"
            await until(lambda: states[2].transaction_id == 102)
        finally:
            stop.set()
            try:
                await asyncio.wait_for(task, 5)
            finally:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
        assert states[2].transaction_id is None
        assert states[3].transaction_id is None
        assert 103 in stopped
