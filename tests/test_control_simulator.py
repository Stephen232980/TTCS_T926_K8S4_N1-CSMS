"""Exercise simulator multi-connector commands over an actual WebSocket."""

import asyncio
import json
from contextlib import suppress
from datetime import datetime
from uuid import uuid4

from websockets.asyncio.server import serve

from scripts.ocpp_control_simulator import ConnectorState, meter_samples, run


async def test_smart_charging_profiles_control_real_socket_power_and_energy(tmp_path):
    replies = {}
    ready = asyncio.Event()
    socket_ready = asyncio.get_running_loop().create_future()
    readings = []
    states = {1: ConnectorState()}
    stop = asyncio.Event()
    profile_store = tmp_path / "profiles.json"

    async def handler(socket):
        socket_ready.set_result(socket)
        async for raw in socket:
            frame = json.loads(raw)
            if frame[0] == 3:
                replies.pop(frame[1]).set_result(frame[2])
                continue
            _, uid, action, payload = frame
            response = {}
            if action == "BootNotification":
                response = {"status": "Accepted", "interval": 60}
            elif action == "StatusNotification":
                ready.set()
            elif action == "StartTransaction":
                response = {"transactionId": 101, "idTagInfo": {"status": "Accepted"}}
            elif action == "MeterValues":
                readings.append(payload["meterValue"][0]["sampledValue"])
            await socket.send(json.dumps([3, uid, response]))

    async def command(action, payload):
        socket = await socket_ready
        uid = str(uuid4())
        future = asyncio.get_running_loop().create_future()
        replies[uid] = future
        await socket.send(json.dumps([2, uid, action, payload]))
        return await asyncio.wait_for(future, 5)

    async def until(predicate):
        async with asyncio.timeout(8):
            while not predicate():
                await asyncio.sleep(0.02)

    def profile(watts, transaction=None):
        details = {
            "chargingProfileId": 1 if transaction is None else 2,
            "stackLevel": 0 if transaction is None else 1,
            "chargingProfilePurpose": "TxDefaultProfile"
            if transaction is None
            else "TxProfile",
            "chargingProfileKind": "Absolute",
            "chargingSchedule": {
                "chargingRateUnit": "W",
                "chargingSchedulePeriod": [{"startPeriod": 0, "limit": watts}],
            },
        }
        if transaction is not None:
            details["transactionId"] = transaction
        return {"connectorId": 1, "csChargingProfiles": details}

    async with serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        task = asyncio.create_task(
            run(
                f"ws://127.0.0.1:{port}",
                "POWER",
                None,
                "Accepted",
                False,
                connectors=states,
                start_delay=0,
                stop_event=stop,
                profile_store=profile_store,
            )
        )
        try:
            await asyncio.wait_for(ready.wait(), 5)
            config = await command("GetConfiguration", {})
            assert any(
                row["value"] == "Core,SmartCharging,Reservation"
                for row in config["configurationKey"]
            )
            assert (await command("SetChargingProfile", profile(0)))[
                "status"
            ] == "Accepted"
            assert (
                await command(
                    "RemoteStartTransaction", {"connectorId": 1, "idTag": "TEST"}
                )
            )["status"] == "Accepted"
            await until(lambda: readings)
            assert (
                next(
                    sample
                    for sample in readings[-1]
                    if sample["measurand"] == "Power.Active.Import"
                )["value"]
                == "0"
            )
            assert states[1].meter_wh == 1000
            assert (await command("SetChargingProfile", profile(6000, 101)))[
                "status"
            ] == "Accepted"
            await until(lambda: states[1].meter_wh > 1000)
            assert (
                next(
                    sample
                    for sample in readings[-1]
                    if sample["measurand"] == "Power.Active.Import"
                )["value"]
                == "6000"
            )
            composite = await command("GetCompositeSchedule", {"connectorId": 1})
            assert (
                composite["chargingSchedule"]["chargingSchedulePeriod"][0]["limit"]
                == 6000
            )
            assert (await command("SetChargingProfile", profile(22000, 999)))[
                "status"
            ] == "Rejected"
            assert states[1].offered_watts == 6000
            assert (await command("SetChargingProfile", profile(3000, 101)))[
                "status"
            ] == "Accepted"
            before = states[1].meter_wh
            await until(lambda: states[1].meter_wh > before)
            assert (
                next(
                    sample
                    for sample in readings[-1]
                    if sample["measurand"] == "Power.Active.Import"
                )["value"]
                == "3000"
            )
            assert (await command("RemoteStopTransaction", {"transactionId": 101}))[
                "status"
            ] == "Accepted"
            await until(lambda: states[1].transaction_id is None)
            assert states[1].offered_watts == 0
            retained = json.loads(profile_store.read_text(encoding="utf-8"))["1"]
            assert retained["default_limit_w"] == 0
            assert retained["transaction_limit_w"] is None
        finally:
            stop.set()
            await asyncio.wait_for(task, 5)


async def test_simulator_restart_loads_zero_baseline_before_any_transaction(tmp_path):
    store = tmp_path / "retained.json"
    store.write_text(
        json.dumps(
            {
                "1": {
                    "default_limit_w": 0,
                    "default_profile_id": 2,
                    "transaction_id": 101,
                    "transaction_limit_w": 6000,
                    "transaction_profile_id": 3,
                }
            }
        ),
        encoding="utf-8",
    )
    ready = asyncio.Event()
    stop = asyncio.Event()
    states = {1: ConnectorState()}

    async def handler(socket):
        async for raw in socket:
            frame = json.loads(raw)
            if frame[0] != 2:
                continue
            _, uid, action, _ = frame
            await socket.send(
                json.dumps(
                    [
                        3,
                        uid,
                        {"status": "Accepted", "interval": 60}
                        if action == "BootNotification"
                        else {},
                    ]
                )
            )
            if action == "StatusNotification":
                ready.set()

    async with serve(handler, "127.0.0.1", 0) as server:
        task = asyncio.create_task(
            run(
                f"ws://127.0.0.1:{server.sockets[0].getsockname()[1]}",
                "RESTART",
                None,
                "Accepted",
                False,
                connectors=states,
                stop_event=stop,
                profile_store=store,
            )
        )
        try:
            await asyncio.wait_for(ready.wait(), 5)
            assert states[1].offered_watts == 0
            assert states[1].default_profile_id == 2
            assert states[1].transaction_limit_w is None
            assert meter_samples(states[1], 5)[0]["value"] == "1000"
        finally:
            stop.set()
            await asyncio.wait_for(task, 5)


def test_meter_telemetry_integrates_energy_and_keeps_connectors_independent():
    state = ConnectorState()
    other = ConnectorState()
    first = {s["measurand"]: s for s in meter_samples(state, 10)}
    assert first["Energy.Active.Import.Register"]["value"] == "1020"
    assert first["Power.Active.Import"] == {
        "measurand": "Power.Active.Import",
        "value": "7200",
        "unit": "W",
    }
    assert set(first) == {
        "Energy.Active.Import.Register",
        "Power.Active.Import",
        "Temperature",
        "Voltage",
        "Current.Import",
        "SoC",
        "Frequency",
    }
    second = {s["measurand"]: s for s in meter_samples(state, 10)}
    assert second["Energy.Active.Import.Register"]["value"] == "1040"
    assert other.meter_wh == 1000
    assert meter_samples(other, 10)[0]["value"] == "1020"


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
                assert (
                    datetime.fromisoformat(payload["timestamp"]).utcoffset() is not None
                )
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
            for number in (2, 3):
                readings = {
                    s["measurand"]: s
                    for s in meters[number]["meterValue"][0]["sampledValue"]
                }
                assert {
                    "Power.Active.Import",
                    "Temperature",
                    "Voltage",
                    "Current.Import",
                    "SoC",
                    "Frequency",
                } <= readings.keys()
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
