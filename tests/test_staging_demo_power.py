"""The mounted staging demo must enforce profiles, not merely acknowledge them."""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from websockets.asyncio.server import serve

from scripts import ocpp_control_simulator as control
from scripts import staging_demo as demo
from scripts.ocpp_control_simulator import ConnectorState


def profile(number, watts, tx=None, profile_id=None):
    details = {
        "chargingProfileId": profile_id
        if profile_id is not None
        else number * 2 + int(tx is not None),
        "stackLevel": 0 if tx is None else 1,
        "chargingProfilePurpose": "TxDefaultProfile" if tx is None else "TxProfile",
        "chargingProfileKind": "Absolute",
        "chargingSchedule": {
            "chargingRateUnit": "W",
            "chargingSchedulePeriod": [{"startPeriod": 0, "limit": watts}],
        },
    }
    if tx is not None:
        details["transactionId"] = tx
    return {"connectorId": number, "csChargingProfiles": details}


@pytest.fixture
async def wire(tmp_path, monkeypatch):
    monkeypatch.setattr(demo, "ROOT", tmp_path)
    monkeypatch.setattr(demo, "STOP", tmp_path / "stop.request")
    monkeypatch.setattr(
        control,
        "load_connectors",
        AsyncMock(return_value={n: ConnectorState() for n in (1, 2, 3)}),
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

    monkeypatch.setattr(demo, "SessionFactory", Database)
    active = {}
    requests = {}
    readings = []
    starts = []
    stops = []
    notices = []
    tasks = []
    count = 100

    async def handler(socket):
        nonlocal count
        active["socket"] = socket
        async for raw in socket:
            frame = json.loads(raw)
            if frame[0] == 3:
                requests[frame[1]].set_result(frame[2])
                continue
            _, uid, action, body = frame
            response = {"status": "Accepted"}
            if action == "StartTransaction":
                count += 1
                starts.append(body)
                response = {"transactionId": count, "idTagInfo": {"status": "Accepted"}}
            elif action == "StopTransaction":
                stops.append(body)
            elif action == "MeterValues":
                readings.append(body)
            elif action == "StatusNotification":
                notices.append(body)
            await socket.send(json.dumps([3, uid, response]))

    async def until(predicate):
        async with asyncio.timeout(5):
            while not predicate():
                await asyncio.sleep(0.01)

    async def command(action, payload):
        uid = str(uuid4())
        future = asyncio.get_running_loop().create_future()
        requests[uid] = future
        await active["socket"].send(json.dumps([2, uid, action, payload]))
        return await asyncio.wait_for(future, 5)

    async def boot():
        charger = demo.Charger({"code": "DEMO-STG-TEST-001", "fault_connector": None})
        tasks.append(asyncio.create_task(charger.run()))
        await until(lambda: charger.online)
        return charger

    async with serve(handler, "127.0.0.1", 0) as server:
        monkeypatch.setattr(
            demo, "OCPP", f"ws://127.0.0.1:{server.sockets[0].getsockname()[1]}"
        )
        charger = await boot()
        try:
            yield SimpleNamespace(
                charger=charger,
                command=command,
                until=until,
                readings=readings,
                starts=starts,
                stops=stops,
                notices=notices,
                tasks=tasks,
                boot=boot,
            )
        finally:
            demo.STOP.touch()
            for task in tasks:
                if not task.done():
                    await asyncio.wait_for(task, 12)


async def test_real_wire_profiles_bound_multi_start_power_and_energy(wire, monkeypatch):
    c = wire.charger
    config = await wire.command(
        "GetConfiguration",
        {
            "key": [
                "SupportedFeatureProfiles",
                "ChargingScheduleAllowedChargingRateUnit",
                "ChargeProfileMaxStackLevel",
            ]
        },
    )
    values = {r["key"]: r["value"] for r in config["configurationKey"]}
    assert "SmartCharging" in values["SupportedFeatureProfiles"].split(",")
    assert "Reservation" in values["SupportedFeatureProfiles"].split(",")
    assert (
        values["ChargingScheduleAllowedChargingRateUnit"] == "Power"
        and values["ChargeProfileMaxStackLevel"] == "1"
    )
    for n in (1, 2, 3):
        assert await wire.command("SetChargingProfile", profile(n, 0)) == {
            "status": "Accepted"
        }
    replies = await asyncio.gather(
        *(
            wire.command(
                "RemoteStartTransaction", {"connectorId": n, "idTag": "PRIVATE"}
            )
            for n in (1, 2, 3)
        )
    )
    assert all(r["status"] == "Accepted" for r in replies)
    await wire.until(lambda: len(c.transactions) == 3)
    await wire.until(
        lambda: all(c.power_state(n).last_meter_at is not None for n in (1, 2, 3))
    )
    tick = [100.0]
    monkeypatch.setattr(demo, "monotonic", lambda: tick[0])
    for state in c.telemetry.values():
        state.last_meter_at = tick[0]
    tick[0] += 20
    await c.meter_values()
    assert all(c.meters[n] == 1000 for n in (1, 2, 3))
    for n in (1, 2, 3):
        assert await wire.command(
            "SetChargingProfile", profile(n, 1000, c.transactions[n])
        ) == {"status": "Accepted"}
    tick[0] += 36
    await c.meter_values()
    snapshots = wire.readings[-3:]
    powers = [
        int(
            next(
                s["value"]
                for s in r["meterValue"][0]["sampledValue"]
                if s["measurand"] == "Power.Active.Import"
            )
        )
        for r in snapshots
    ]
    assert sum(powers) == 3000
    assert all(c.meters[n] == 1010 for n in (1, 2, 3))
    # Integrate under the old profile until the change, then under the new one.
    tick[0] += 36
    assert await wire.command(
        "SetChargingProfile", profile(1, 500, c.transactions[1])
    ) == {"status": "Accepted"}
    tick[0] += 72
    await c.meter_values()
    assert c.meters[1] == 1030  # 10 Wh before and 10 Wh after the reduction.
    composite = await wire.command(
        "GetCompositeSchedule",
        {"connectorId": 1, "duration": 60, "chargingRateUnit": "W"},
    )
    assert composite["chargingSchedule"]["chargingSchedulePeriod"] == [
        {"startPeriod": 0, "limit": 500}
    ]
    # Stop at the profile-bound meter value; retain the default 0 W for the next car.
    tick[0] += 72
    await c.stop("EVDisconnected", 1)
    assert wire.stops[-1]["meterStop"] == 1040
    assert c.power_state(1).offered_watts == 0


async def test_actual_demo_restart_restores_profiles_before_boot_and_start(
    wire, monkeypatch
):
    c = wire.charger
    assert await wire.command("SetChargingProfile", profile(1, 0)) == {
        "status": "Accepted"
    }
    await wire.command("RemoteStartTransaction", {"connectorId": 1, "idTag": "PRIVATE"})
    await wire.until(lambda: c.transactions.get(1) is not None)
    tx = c.transactions[1]
    assert await wire.command("SetChargingProfile", profile(1, 1200, tx)) == {
        "status": "Accepted"
    }
    wire.tasks[-1].cancel()
    await asyncio.gather(wire.tasks[-1], return_exceptions=True)
    # Reconstruct independent connector objects, as load_connectors does from DB.
    monkeypatch.setattr(
        control,
        "load_connectors",
        AsyncMock(
            return_value={
                1: ConnectorState(
                    status="Charging", transaction_id=tx, meter_wh=c.meters[1]
                ),
                2: ConnectorState(),
                3: ConnectorState(),
            }
        ),
    )
    reboot = await wire.boot()
    schedule = await wire.command(
        "GetCompositeSchedule", {"connectorId": 1, "duration": 60}
    )
    assert schedule["chargingSchedule"]["chargingSchedulePeriod"][0]["limit"] == 1200
    assert reboot.power_state(1).default_limit_w == 0
    assert await wire.command("ClearChargingProfile", {"id": tx + 9999}) == {
        "status": "Unknown"
    }
    assert await wire.command("ClearChargingProfile", {"id": 3}) == {
        "status": "Accepted"
    }
    assert reboot.power_state(1).offered_watts == 0
    await reboot.stop("EVDisconnected", 1)
    await wire.command("RemoteStartTransaction", {"connectorId": 1, "idTag": "PRIVATE"})
    await wire.until(lambda: reboot.transactions.get(1) not in (None, tx))
    assert reboot.power_state(1).offered_watts == 0


@pytest.fixture
def charger(tmp_path, monkeypatch):
    monkeypatch.setattr(demo, "ROOT", tmp_path)
    return demo.Charger({"code": "DEMO-STG-TEST-001", "fault_connector": None})


@pytest.mark.parametrize(
    "kind",
    [
        "wrong_transaction",
        "no_transaction",
        "ampere",
        "negative",
        "bool_limit",
        "bool_stack",
        "future",
        "multiple_periods",
        "bad_period",
        "bad_schedule",
        "bad_profile",
        "stack",
        "recurring",
    ],
)
def test_unsupported_profiles_are_rejected_without_changing_baseline(charger, kind):
    assert charger.power_command("SetChargingProfile", profile(1, 0)) == {
        "status": "Accepted"
    }
    charger.transactions[1] = 10
    body = profile(1, 2000, 10)
    details = body["csChargingProfiles"]
    schedule = details["chargingSchedule"]
    if kind == "wrong_transaction":
        details["transactionId"] = 11
    elif kind == "no_transaction":
        charger.transactions.clear()
    elif kind == "ampere":
        schedule["chargingRateUnit"] = "A"
    elif kind == "negative":
        schedule["chargingSchedulePeriod"][0]["limit"] = -1
    elif kind == "bool_limit":
        schedule["chargingSchedulePeriod"][0]["limit"] = True
    elif kind == "bool_stack":
        details["stackLevel"] = True
    elif kind == "future":
        details["validFrom"] = datetime.now(UTC).isoformat()
    elif kind == "multiple_periods":
        schedule["chargingSchedulePeriod"].append({"startPeriod": 30, "limit": 3000})
    elif kind == "bad_period":
        schedule["chargingSchedulePeriod"][0] = None
    elif kind == "bad_schedule":
        details["chargingSchedule"] = None
    elif kind == "bad_profile":
        body["csChargingProfiles"] = None
    elif kind == "stack":
        details["stackLevel"] = 0
    elif kind == "recurring":
        details["chargingProfileKind"] = "Recurring"
    assert charger.power_command("SetChargingProfile", body) == {"status": "Rejected"}
    assert charger.power_state(1).offered_watts == 0


def test_persistence_failure_rejects_and_keeps_previous_budget(charger, monkeypatch):
    assert charger.power_command("SetChargingProfile", profile(1, 0)) == {
        "status": "Accepted"
    }
    charger.transactions[1] = 10

    def fail():
        raise OSError("disk full")

    monkeypatch.setattr(charger, "save_power_profiles", fail)
    assert charger.power_command("SetChargingProfile", profile(1, 2000, 10)) == {
        "status": "Rejected"
    }
    assert charger.power_state(1).offered_watts == 0


def test_corrupt_profile_store_fails_closed(charger, tmp_path):
    (tmp_path / "DEMO-STG-TEST-001.power.private.json").write_text(
        '{"version":1,"connectors":{"1":{"default_limit_w":0}}}'
    )
    with pytest.raises(RuntimeError, match="Incomplete persisted"):
        charger.load_power_profiles()


async def test_reservation_ownership_survives_start_under_zero_baseline(charger):
    charger.status = AsyncMock()
    expiry = (datetime.now(UTC) + timedelta(minutes=15)).isoformat()
    result = charger.reservation_command(
        "ReserveNow",
        {
            "connectorId": 1,
            "idTag": "PRIVATE",
            "reservationId": 45,
            "expiryDate": expiry,
        },
    )
    assert result == {"status": "Accepted"}
    await asyncio.gather(*charger.tasks)
    assert charger.reservation_command(
        "ReserveNow",
        {"connectorId": 1, "idTag": "OTHER", "reservationId": 46, "expiryDate": expiry},
    ) == {"status": "Occupied"}
    charger.call = AsyncMock(
        return_value={"transactionId": 101, "idTagInfo": {"status": "Accepted"}}
    )
    assert charger.power_command("SetChargingProfile", profile(1, 0)) == {
        "status": "Accepted"
    }
    await charger.start("OTHER", 1)
    charger.call.assert_not_awaited()
    await charger.start("PRIVATE", 1)
    assert charger.call.await_args_list[0].args[1]["reservationId"] == 45
    assert charger.power_state(1).offered_watts == 0
    assert not charger.reservations


async def test_reservation_survives_demo_restart_on_real_wire(wire, monkeypatch):
    expiry = (datetime.now(UTC) + timedelta(minutes=15)).isoformat()
    reserve = {
        "connectorId": 2,
        "idTag": "PRIVATE",
        "reservationId": 51,
        "expiryDate": expiry,
    }
    assert await wire.command("SetChargingProfile", profile(2, 0)) == {
        "status": "Accepted"
    }
    assert await wire.command("ReserveNow", reserve) == {"status": "Accepted"}
    assert await wire.command(
        "ReserveNow", dict(reserve, idTag="OTHER", reservationId=52)
    ) == {"status": "Occupied"}
    wire.tasks[-1].cancel()
    await asyncio.gather(wire.tasks[-1], return_exceptions=True)
    monkeypatch.setattr(
        control,
        "load_connectors",
        AsyncMock(return_value={n: ConnectorState() for n in (1, 2, 3)}),
    )
    reboot = await wire.boot()
    assert reboot.reservations[2]["reservationId"] == 51
    assert await wire.command(
        "RemoteStartTransaction", {"connectorId": 2, "idTag": "OTHER"}
    ) == {"status": "Rejected"}
    assert await wire.command(
        "RemoteStartTransaction", {"connectorId": 2, "idTag": "PRIVATE"}
    ) == {"status": "Accepted"}
    await wire.until(lambda: 2 in reboot.transactions)
    assert wire.starts[-1]["reservationId"] == 51
    assert reboot.power_state(2).offered_watts == 0
    assert not reboot.reservations
    await reboot.stop("EVDisconnected", 2)
    assert await wire.command("ReserveNow", dict(reserve, reservationId=52)) == {
        "status": "Accepted"
    }
    assert await wire.command("CancelReservation", {"reservationId": 52}) == {
        "status": "Accepted"
    }
    await wire.until(lambda: not reboot.reservations)


def test_old_transaction_limit_is_not_reused_for_a_new_car(charger):
    assert charger.power_command("SetChargingProfile", profile(1, 0)) == {
        "status": "Accepted"
    }
    charger.transactions[1] = 10
    assert charger.power_command("SetChargingProfile", profile(1, 2000, 10)) == {
        "status": "Accepted"
    }
    fresh = demo.Charger(charger.config)
    fresh.transactions[1] = 11
    fresh.load_power_profiles()
    assert fresh.power_state(1).offered_watts == 0
    assert fresh.power_state(1).transaction_profile_id is None
