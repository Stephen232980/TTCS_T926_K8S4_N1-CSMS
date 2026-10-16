"""G1 budgets: source-independent answers, PostgreSQL races and device failures."""

import asyncio
import os
import subprocess
import sys
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from time import monotonic
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError
from sqlalchemy import func, select

from src.entrypoints.http import app
from src.modules.charging.models import ChargingSession
from src.modules.identity.authorization import (
    ActorScope,
    AuthorizationEvidence,
    CurrentActor,
)
from src.modules.identity.dependencies import get_current_actor
from src.modules.power import worker
from src.modules.power.allocation import allocate_watts
from src.modules.power.models import ConnectorPower, PowerCommand, StationPower
from src.modules.power.schemas import PowerSetting
from src.modules.power.service import (
    change_control,
    note_power_event,
    note_power_start,
    power_start_allowed,
    save_settings,
)
from src.modules.stations.models import ChargePoint, Connector
from tests.test_flat_tariff_api import api_db, committed_tariff_db  # noqa: F401
from tests.test_tariff_schema import make_station


@pytest.mark.parametrize(
    "budget,ratings,expected",
    [
        (30000, [7000, 22000, 22000], [7000, 11500, 11500]),
        (30000, [22000] * 3, [10000] * 3),
        (30000, [22000] * 2, [15000] * 2),
        (1, [22000] * 3, [0] * 3),
        (0, [5, 5], [0, 0]),
        (40000, [5000, 7000], [5000, 7000]),
    ],
)
def test_allocation_hand_answers(budget, ratings, expected):
    keys = [UUID(int=i + 1) for i in range(len(ratings))]
    assert list(allocate_watts(budget, dict(zip(keys, ratings))).values()) == expected


@pytest.mark.parametrize("budget", range(1, 51))
def test_allocator_conserves_budget_and_respects_each_ceiling(budget):
    demands = {UUID(int=i + 1): i + 3 for i in range(20)}
    result = allocate_watts(budget, demands)
    assert sum(result.values()) <= budget
    assert all(0 <= result[key] <= value for key, value in demands.items())


@pytest.mark.parametrize(
    "value", [True, 0, -1, "NaN", "Infinity", "0.0001", "1000000", None]
)
def test_config_rejects_invalid_kw(value):
    with pytest.raises(ValidationError):
        PowerSetting.model_validate(
            {
                "version": 0,
                "limit_kw": value,
                "connectors": [{"connector_id": str(uuid4()), "rated_kw": "22"}],
            }
        )


@pytest.fixture
async def fleet(api_db, monkeypatch):  # noqa: F811 - imported pytest fixture
    factory = api_db
    monkeypatch.setattr(worker, "SessionFactory", factory)
    monkeypatch.setattr(worker, "engine", factory.kw["bind"])
    async with factory() as db, db.begin():
        station = await make_station(db)
        station.status = "active"
        now = datetime.now(UTC)
        charger = ChargePoint(
            station_id=station.id,
            code=f"POWER-{uuid4().hex[:10]}",
            status="online",
            last_seen_at=now,
            last_boot_at=now,
            heartbeat_interval_seconds=600,
        )
        db.add(charger)
        await db.flush()
        connectors = [
            Connector(
                charge_point_id=charger.id,
                connector_number=i + 1,
                status="Available",
                raw_ocpp_status="Available",
                max_power_kw=Decimal(22),
            )
            for i in range(3)
        ]
        db.add_all(connectors)
        await db.flush()
        ids = [c.id for c in connectors]
        scope = ActorScope(station.owner_id, station.owner_id)
        evidence = AuthorizationEvidence("owner.power.configure", ("station_owner",))
    return factory, station, charger, ids, scope, evidence


def body(ids, version=0, limit="30"):
    return PowerSetting.model_validate(
        {
            "version": version,
            "limit_kw": limit,
            "connectors": [{"connector_id": str(id_), "rated_kw": "22"} for id_ in ids],
            "zero_limit_verified": True,
            "offline_retention_verified": True,
            "verification_note": "G1 simulator; zero, offline retention and reboot commissioning passed",
        }
    )


async def configure(fleet):
    factory, station, _, ids, scope, evidence = fleet
    async with factory() as db, db.begin():
        await save_settings(db, station.id, body(ids), scope, evidence)
        await change_control(db, station.id, 1, True, scope, evidence)
        config = await db.get(StationPower, station.id)
        config.dirty_at = datetime.now(UTC) - timedelta(seconds=3)


async def run_plan(factory, station):
    async with factory() as db, db.begin():
        config = await db.get(StationPower, station.id)
        config.last_plan_at = None
        config.dirty_at = None
    await worker.reconcile_station(station.id)


def device_wire(monkeypatch, charger):
    state = {i: 0 for i in range(1, 4)}
    trace = []
    failures = set()
    connection = SimpleNamespace(boot_accepted=True)

    async def snapshot():
        return {charger.id: connection}

    async def get(code):
        return connection

    async def wire(connection, action, payload, request_id):
        trace.append((action, payload))
        if action in failures:
            return "Rejected", {}
        if action == "GetConfiguration":
            return "Accepted", {
                "configurationKey": [
                    {"key": "SupportedFeatureProfiles", "value": "Core,SmartCharging"},
                    {
                        "key": "ChargingScheduleAllowedChargingRateUnit",
                        "value": "Power",
                    },
                    {"key": "ChargeProfileMaxStackLevel", "value": "1"},
                ]
            }
        if action == "SetChargingProfile":
            state[payload["connectorId"]] = payload["csChargingProfiles"][
                "chargingSchedule"
            ]["chargingSchedulePeriod"][0]["limit"]
        if action == "GetCompositeSchedule":
            return "Accepted", {
                "connectorId": payload["connectorId"],
                "scheduleStart": datetime.now(UTC).isoformat(),
                "chargingSchedule": {
                    "duration": 60,
                    "chargingRateUnit": "W",
                    "chargingSchedulePeriod": [
                        {"startPeriod": 0, "limit": state[payload["connectorId"]]}
                    ],
                },
            }
        return "Accepted", {}

    monkeypatch.setattr(worker.ocpp_connections, "snapshot", snapshot)
    monkeypatch.setattr(worker.ocpp_connections, "get", get)
    monkeypatch.setattr(worker, "wire", wire)
    return state, trace, failures


def real_demo_profiles(fleet, monkeypatch, tmp_path):
    """Use the reviewed device parser, not an adapter accepting every profile."""
    from scripts import staging_demo as demo

    factory, _, charger, _, _, _ = fleet
    monkeypatch.setattr(demo, "ROOT", tmp_path)
    device = demo.Charger({"code": charger.code, "fault_connector": None})
    connection = SimpleNamespace(boot_accepted=True)
    trace = []

    async def snapshot():
        return {charger.id: connection}

    async def get(code):
        return connection

    async def wire(connection, action, payload, request_id):
        async with factory() as db:
            active = {
                row.connector_id: row.id
                for row in await db.scalars(
                    select(ChargingSession).where(ChargingSession.ended_at.is_(None))
                )
            }
            connectors = list(
                await db.scalars(
                    select(Connector).where(Connector.charge_point_id == charger.id)
                )
            )
        for connector in connectors:
            number = connector.connector_number
            tx = active.get(connector.id)
            state = device.power_state(number)
            if device.transactions.get(number) != tx:
                state.transaction_limit_w = state.transaction_profile_id = None
            if tx is None:
                device.transactions.pop(number, None)
            else:
                device.transactions[number] = tx
        response = (
            device.reservation_command(action, payload)
            if action == "GetConfiguration"
            else device.power_command(action, payload)
        )
        trace.append((action, payload, response))
        return (
            "Accepted" if action == "GetConfiguration" else response["status"],
            response,
        )

    monkeypatch.setattr(worker.ocpp_connections, "snapshot", snapshot)
    monkeypatch.setattr(worker.ocpp_connections, "get", get)
    monkeypatch.setattr(worker, "wire", wire)
    return device, trace


async def test_stop_to_idle_profile_is_supported_by_actual_staging_demo(
    fleet, monkeypatch, tmp_path
):
    factory, station, _, ids, _, _ = fleet
    device, trace = real_demo_profiles(fleet, monkeypatch, tmp_path)
    await configure(fleet)
    await run_plan(factory, station)
    await sessions(fleet)
    await run_plan(factory, station)
    assert [device.power_state(n).offered_watts for n in (1, 2, 3)] == [10000] * 3
    async with factory() as db, db.begin():
        for transaction in await db.scalars(
            select(ChargingSession).where(ChargingSession.connector_id.in_(ids))
        ):
            transaction.ended_at = datetime.now(UTC)
        for connector_id in ids:
            (await db.get(Connector, connector_id)).raw_ocpp_status = "Available"
    trace.clear()
    await run_plan(factory, station)
    async with factory() as db:
        assert (await db.get(StationPower, station.id)).state == "ready"
        assert await db.scalar(select(func.sum(ConnectorPower.reserved_w))) == 0
    writes = [(p, r) for action, p, r in trace if action == "SetChargingProfile"]
    assert len(writes) == 3
    assert all(p["csChargingProfiles"]["stackLevel"] == 0 for p, _ in writes)
    assert all(r["status"] == "Accepted" for _, r in writes)
    assert [device.power_state(n).offered_watts for n in (1, 2, 3)] == [0] * 3


async def test_fast_new_transaction_requires_fresh_profile_at_same_watts(
    fleet, monkeypatch, tmp_path
):
    factory, station, charger, ids, _, _ = fleet
    device, trace = real_demo_profiles(fleet, monkeypatch, tmp_path)
    await configure(fleet)
    await run_plan(factory, station)
    await sessions(fleet)
    await run_plan(factory, station)
    async with factory() as db, db.begin():
        old = await db.scalar(
            select(ChargingSession).where(ChargingSession.connector_id == ids[0])
        )
        old.ended_at = datetime.now(UTC)
        new = ChargingSession(
            charge_point_id=charger.id,
            connector_id=ids[0],
            driver_id=station.owner_id,
            tag_tail="NEXT",
            authorization_status="Accepted",
            started_at=datetime.now(UTC),
            meter_start_wh=Decimal(1000),
        )
        db.add(new)
        await db.flush()
        await note_power_start(db, station.id, ids[0])
        await note_power_event(db, station.id)
        cap = await db.get(ConnectorPower, ids[0])
        assert cap.confirmed_w == 0 and cap.reserved_w == 10000
        new_id = new.id
    trace.clear()
    await run_plan(factory, station)
    writes = [p for action, p, _ in trace if action == "SetChargingProfile"]
    assert len(writes) == 1
    assert writes[0]["csChargingProfiles"]["transactionId"] == new_id
    assert (
        writes[0]["csChargingProfiles"]["chargingSchedule"]["chargingSchedulePeriod"][
            0
        ]["limit"]
        == 10000
    )
    assert device.power_state(1).offered_watts == 10000
    async with factory() as db:
        cap = await db.get(ConnectorPower, ids[0])
        assert cap.confirmed_w == cap.reserved_w == 10000


async def test_late_old_readback_cannot_reconfirm_power_for_new_transaction(
    fleet, monkeypatch, tmp_path
):
    factory, station, charger, ids, _, _ = fleet
    real_demo_profiles(fleet, monkeypatch, tmp_path)
    await configure(fleet)
    await run_plan(factory, station)
    await sessions(fleet)
    await run_plan(factory, station)
    old_device = next(d for d in await worker.devices(station.id) if d.number == 1)
    original = worker.wire
    replaced = False

    async def turnover(connection, action, payload, request_id):
        nonlocal replaced
        response = await original(connection, action, payload, request_id)
        if action == "GetCompositeSchedule" and not replaced:
            replaced = True
            async with factory() as db, db.begin():
                old = await db.get(ChargingSession, old_device.transaction_id)
                old.ended_at = datetime.now(UTC)
                db.add(
                    ChargingSession(
                        charge_point_id=charger.id,
                        connector_id=ids[0],
                        driver_id=station.owner_id,
                        tag_tail="RACE",
                        authorization_status="Accepted",
                        started_at=datetime.now(UTC),
                        meter_start_wh=Decimal(1000),
                    )
                )
                await db.flush()
                await note_power_start(db, station.id, ids[0])
                await note_power_event(db, station.id)
        return response

    monkeypatch.setattr(worker, "wire", turnover)
    async with factory() as db:
        generation = (await db.get(StationPower, station.id)).generation
    assert not await worker.set_limit(old_device, station.id, generation, 10000)
    async with factory() as db:
        cap = await db.get(ConnectorPower, ids[0])
        assert cap.confirmed_w == 0 and cap.reserved_w == 10000
        assert cap.pending_command_id is not None
    await run_plan(factory, station)
    async with factory() as db:
        cap = await db.get(ConnectorPower, ids[0])
        assert cap.confirmed_w == cap.reserved_w == 10000


async def sessions(fleet):
    factory, station, charger, ids, _, _ = fleet
    async with factory() as db, db.begin():
        for id_ in ids:
            db.add(
                ChargingSession(
                    charge_point_id=charger.id,
                    connector_id=id_,
                    driver_id=station.owner_id,
                    tag_tail="TEST",
                    authorization_status="Accepted",
                    started_at=datetime.now(UTC),
                    meter_start_wh=Decimal(1000),
                )
            )
            connector = await db.get(Connector, id_)
            connector.raw_ocpp_status = "Charging"
    return ids


async def test_bootstrap_then_reduce_before_increase_and_no_duplicate_profiles(
    fleet, monkeypatch
):
    factory, station, charger, ids, _, _ = fleet
    state, trace, _ = device_wire(monkeypatch, charger)
    await configure(fleet)
    await run_plan(factory, station)
    async with factory() as db:
        assert await power_start_allowed(db, station.id)
    await sessions(fleet)
    await run_plan(factory, station)
    assert list(state.values()) == [10000] * 3
    async with factory() as db, db.begin():
        connector = await db.get(Connector, ids[0])
        connector.raw_ocpp_status = "SuspendedEV"
    trace.clear()
    await run_plan(factory, station)
    writes = [p for action, p in trace if action == "SetChargingProfile"]
    assert writes[0]["connectorId"] == 1 and state == {1: 0, 2: 15000, 3: 15000}
    trace.clear()
    await run_plan(factory, station)
    assert not any(action == "SetChargingProfile" for action, _ in trace)


async def test_uncertain_increase_keeps_reserved_budget_and_blocks_all_start_paths(
    fleet, monkeypatch
):
    factory, station, charger, _, _, _ = fleet
    state, trace, failures = device_wire(monkeypatch, charger)
    await configure(fleet)
    await run_plan(factory, station)
    await sessions(fleet)
    failures.add("GetCompositeSchedule")
    await run_plan(factory, station)
    async with factory() as db:
        config = await db.get(StationPower, station.id)
        assert config.state == "degraded"
        assert not await power_start_allowed(db, station.id)
        assert (
            await db.scalar(
                select(func.sum(ConnectorPower.reserved_w)).where(
                    ConnectorPower.station_id == station.id
                )
            )
            == 10000
        )
        assert (
            await db.scalar(
                select(func.count())
                .select_from(PowerCommand)
                .where(PowerCommand.action == "RemoteStopTransaction")
            )
            == 1
        )
    assert sum(state.values()) == 10000
    assert any(action == "RemoteStopTransaction" for action, _ in trace)
    failures.clear()
    await run_plan(factory, station)
    assert sum(state.values()) == 30000


async def test_offline_power_is_not_lent_to_remaining_connectors(fleet, monkeypatch):
    factory, station, charger, _, _, _ = fleet
    state, _, _ = device_wire(monkeypatch, charger)
    await configure(fleet)
    await run_plan(factory, station)
    await sessions(fleet)
    await run_plan(factory, station)

    async def none():
        return {}

    monkeypatch.setattr(worker.ocpp_connections, "snapshot", none)
    await run_plan(factory, station)
    async with factory() as db:
        config = await db.get(StationPower, station.id)
        assert config.issue == "offline_budget_retained"
        assert await db.scalar(select(func.sum(ConnectorPower.reserved_w))) == 30000
        assert not await power_start_allowed(db, station.id)
    assert sum(state.values()) == 30000


async def test_config_owned_reload_and_version_race(fleet):
    factory, station, _, ids, scope, evidence = fleet
    actor = CurrentActor(station.owner_id, frozenset({"station_owner"}))
    app.dependency_overrides[get_current_actor] = lambda: actor
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            payload = body(ids).model_dump(mode="json")
            saved = await client.put(
                f"/api/v1/owner/stations/{station.id}/power-config", json=payload
            )
            assert saved.status_code == 200 and saved.json()["over_registered"]
            reload = await client.get(
                f"/api/v1/owner/stations/{station.id}/power-config"
            )
            assert (
                reload.json()["limit_kw"] == "30"
                and len(reload.json()["connectors"]) == 3
            )
            app.dependency_overrides[get_current_actor] = lambda: CurrentActor(
                uuid4(), frozenset({"station_owner"})
            )
            assert (
                await client.get(f"/api/v1/owner/stations/{station.id}/power-config")
            ).status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_actor, None)

    async def save():
        try:
            async with factory() as db, db.begin():
                await save_settings(db, station.id, body(ids, 1, "25"), scope, evidence)
            return "saved"
        except HTTPException as error:
            return getattr(error, "status_code", None)

    results = await asyncio.gather(*(save() for _ in range(20)))
    assert results.count("saved") == 1 and results.count(409) == 19


async def test_new_connector_and_reboot_require_commissioning_again(fleet, monkeypatch):
    factory, station, charger, _, _, _ = fleet
    device_wire(monkeypatch, charger)
    await configure(fleet)
    await run_plan(factory, station)
    async with factory() as db, db.begin():
        point = await db.get(ChargePoint, charger.id)
        point.last_boot_at = datetime.now(UTC)
    async with factory() as db:
        assert not await power_start_allowed(db, station.id)
    await run_plan(factory, station)
    async with factory() as db, db.begin():
        db.add(
            Connector(
                charge_point_id=charger.id, connector_number=4, status="Available"
            )
        )
    async with factory() as db:
        assert not await power_start_allowed(db, station.id)


async def test_migration_roundtrip_preserves_existing_station(fleet):
    factory, station, _, _, _, _ = fleet
    url = factory.kw["bind"].url.render_as_string(hide_password=False)
    env = os.environ | {"DATABASE_URL": url}
    for command in (["downgrade", "f200020a2026"], ["upgrade", "head"]):
        await asyncio.to_thread(
            subprocess.run,
            [sys.executable, "-m", "alembic", *command],
            env=env,
            check=True,
            capture_output=True,
        )
    async with factory() as db:
        from src.modules.stations.models import Station

        assert (await db.get(Station, station.id)).name == station.name


async def test_station_worker_lock_prevents_two_concurrent_bootstrap_plans(
    fleet, monkeypatch
):
    factory, station, charger, _, _, _ = fleet
    _, trace, _ = device_wire(monkeypatch, charger)
    original_wire = worker.wire

    async def delayed_wire(*args):
        await asyncio.sleep(0.05)
        return await original_wire(*args)

    monkeypatch.setattr(worker, "wire", delayed_wire)
    await configure(fleet)
    await asyncio.gather(
        worker.reconcile_station(station.id), worker.reconcile_station(station.id)
    )
    assert sum(action == "SetChargingProfile" for action, _ in trace) == 3
    async with factory() as db:
        assert (await db.get(StationPower, station.id)).state == "ready"


async def test_stale_plan_does_not_increase_after_a_new_status_event(
    fleet, monkeypatch
):
    factory, station, charger, ids, _, _ = fleet
    state, trace, _ = device_wire(monkeypatch, charger)
    await configure(fleet)
    await run_plan(factory, station)
    await sessions(fleet)
    await run_plan(factory, station)
    async with factory() as db, db.begin():
        (await db.get(Connector, ids[0])).raw_ocpp_status = "SuspendedEV"
    original_wire = worker.wire
    changed = False

    async def event_during_reduction(connection, action, payload, request_id):
        nonlocal changed
        result = await original_wire(connection, action, payload, request_id)
        if action == "SetChargingProfile" and not changed:
            changed = True
            async with factory() as db, db.begin():
                config = await db.get(StationPower, station.id)
                config.generation += 1
        return result

    monkeypatch.setattr(worker, "wire", event_during_reduction)
    trace.clear()
    await run_plan(factory, station)
    assert state == {1: 0, 2: 10000, 3: 10000}
    assert sum(action == "SetChargingProfile" for action, _ in trace) == 1
    await run_plan(factory, station)
    assert state == {1: 0, 2: 15000, 3: 15000}


async def test_applying_zero_baseline_allows_start_but_disable_and_degraded_deny(
    fleet, monkeypatch
):
    factory, station, charger, _, _, _ = fleet
    device_wire(monkeypatch, charger)
    await configure(fleet)
    await run_plan(factory, station)
    async with factory() as db, db.begin():
        config = await db.get(StationPower, station.id)
        config.state = "applying"
        assert await power_start_allowed(db, station.id)
        config.state = "degraded"
        assert not await power_start_allowed(db, station.id)
        config.state = "applying"
        config.target_enabled = False
        assert not await power_start_allowed(db, station.id)


@pytest.mark.parametrize("event", ["SuspendedEV", "StopTransaction"])
async def test_ten_connectors_reallocate_with_slow_chargers_within_thirty_seconds(
    fleet, monkeypatch, event
):
    factory, station, charger, ids, _, _ = fleet
    chargers = [charger]
    async with factory() as db, db.begin():
        for index in range(1, 10):
            point = ChargePoint(
                station_id=station.id,
                code=f"DEMO10-{uuid4().hex[:10]}",
                status="online",
                last_seen_at=charger.last_seen_at,
                last_boot_at=charger.last_boot_at,
                heartbeat_interval_seconds=600,
            )
            db.add(point)
            await db.flush()
            chargers.append(point)
            if index < 3:
                connector = await db.get(Connector, ids[index])
                connector.charge_point_id = point.id
                connector.connector_number = 1
            else:
                connector = Connector(
                    charge_point_id=point.id,
                    connector_number=1,
                    status="Available",
                    raw_ocpp_status="Available",
                    max_power_kw=Decimal(22),
                )
                db.add(connector)
                await db.flush()
                ids.append(connector.id)
    connections = {p.id: SimpleNamespace(boot_accepted=True, id=p.id) for p in chargers}
    codes = {p.code.lower(): connections[p.id] for p in chargers}
    watts = dict.fromkeys(connections, 0)
    delay = 0.0
    trace = []
    active = 0
    peak = 0

    async def snapshot():
        return connections

    async def get(code):
        return codes[code]

    async def wire(connection, action, payload, request_id):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        try:
            await asyncio.sleep(delay)
            trace.append((connection.id, action))
            if action == "GetConfiguration":
                return "Accepted", {
                    "configurationKey": [
                        {"key": "SupportedFeatureProfiles", "value": "SmartCharging"},
                        {
                            "key": "ChargingScheduleAllowedChargingRateUnit",
                            "value": "Power",
                        },
                        {"key": "ChargeProfileMaxStackLevel", "value": "1"},
                    ]
                }
            if action == "SetChargingProfile":
                watts[connection.id] = payload["csChargingProfiles"][
                    "chargingSchedule"
                ]["chargingSchedulePeriod"][0]["limit"]
                assert sum(watts.values()) <= 30000
            if action == "GetCompositeSchedule":
                return "Accepted", {
                    "connectorId": 1,
                    "scheduleStart": datetime.now(UTC).isoformat(),
                    "chargingSchedule": {
                        "duration": 60,
                        "chargingRateUnit": "W",
                        "chargingSchedulePeriod": [
                            {"startPeriod": 0, "limit": watts[connection.id]},
                        ],
                    },
                }
            return "Accepted", {}
        finally:
            active -= 1

    monkeypatch.setattr(worker.ocpp_connections, "snapshot", snapshot)
    monkeypatch.setattr(worker.ocpp_connections, "get", get)
    monkeypatch.setattr(worker, "wire", wire)
    await configure(fleet)
    await run_plan(factory, station)
    async with factory() as db, db.begin():
        for point, connector_id in zip(chargers, ids, strict=True):
            db.add(
                ChargingSession(
                    charge_point_id=point.id,
                    connector_id=connector_id,
                    driver_id=station.owner_id,
                    tag_tail="DEMO",
                    authorization_status="Accepted",
                    meter_start_wh=1000,
                    started_at=datetime.now(UTC),
                )
            )
            (await db.get(Connector, connector_id)).raw_ocpp_status = "Charging"
    await run_plan(factory, station)
    assert list(watts.values()) == [3000] * 10
    delay = 2.0  # Each successful device reply is slow, still below the 5 s timeout.
    peak = 0
    trace.clear()
    started = monotonic()
    async with factory() as db, db.begin():
        connector = await db.get(Connector, ids[0])
        connector.raw_ocpp_status = (
            "SuspendedEV" if event == "SuspendedEV" else "Available"
        )
        if event == "StopTransaction":
            session = await db.scalar(
                select(ChargingSession).where(
                    ChargingSession.connector_id == ids[0],
                    ChargingSession.ended_at.is_(None),
                )
            )
            session.ended_at = datetime.now(UTC)
        await note_power_event(db, station.id)
    async with asyncio.timeout(30):
        while True:
            await worker.reconcile_station(station.id)
            if watts[charger.id] == 0 and list(watts.values())[1:] == [3333] * 9:
                async with factory() as db:
                    if (await db.get(StationPower, station.id)).state == "ready":
                        break
            await asyncio.sleep(0.1)
    elapsed = monotonic() - started
    assert elapsed < 30
    assert 1 < peak <= 5
    assert trace[:2] == [
        (charger.id, "SetChargingProfile"),
        (charger.id, "GetCompositeSchedule"),
    ]
    async with factory() as db:
        assert (
            await db.scalar(
                select(func.sum(ConnectorPower.reserved_w)).where(
                    ConnectorPower.station_id == station.id
                )
            )
            == 29997
        )
    trace.clear()
    await run_plan(factory, station)
    assert not trace
    print(
        f"DEMO10 {event} including scheduler gates: {elapsed:.3f}s; peak calls={peak}"
    )


async def test_parallel_increases_reserve_budget_atomically(fleet, monkeypatch):
    factory, station, charger, _, _, _ = fleet
    device_wire(monkeypatch, charger)
    await configure(fleet)
    await run_plan(factory, station)
    inputs = await worker.devices(station.id)
    async with factory() as db:
        generation = (await db.get(StationPower, station.id)).generation
    results = await asyncio.gather(
        *(
            worker.set_limit(device, station.id, generation, 20000)
            for device in inputs[:2]
        )
    )
    assert sorted(results) == [False, True]
    async with factory() as db:
        assert (
            await db.scalar(
                select(func.sum(ConnectorPower.reserved_w)).where(
                    ConnectorPower.station_id == station.id
                )
            )
            == 20000
        )


def phase_device(index):
    stamp = datetime.now(UTC)
    return worker.Device(
        UUID(int=index),
        UUID(int=index),
        str(index),
        1,
        stamp,
        22000,
        index,
        0,
        0,
        stamp,
        None,
        index,
        True,
        True,
    )


@pytest.mark.parametrize(
    "kind",
    [
        "id_bool",
        "duration_missing",
        "duration_short",
        "period_bool",
        "period_negative",
        "unordered",
        "duplicate",
        "nan",
        "infinite",
        "boolean_limit",
    ],
)
async def test_malformed_composite_never_releases_budget(monkeypatch, kind):
    schedule = {
        "duration": 60,
        "chargingRateUnit": "W",
        "chargingSchedulePeriod": [{"startPeriod": 0, "limit": 0}],
    }
    reply = {
        "connectorId": 1,
        "scheduleStart": datetime.now(UTC).isoformat(),
        "chargingSchedule": schedule,
    }
    if kind == "id_bool":
        reply["connectorId"] = True
    elif kind == "duration_missing":
        schedule.pop("duration")
    elif kind == "duration_short":
        schedule["duration"] = 1
    elif kind == "period_bool":
        schedule["chargingSchedulePeriod"][0]["startPeriod"] = False
    elif kind == "period_negative":
        schedule["chargingSchedulePeriod"][0]["startPeriod"] = -1
    elif kind in {"unordered", "duplicate"}:
        schedule["chargingSchedulePeriod"] += [
            {"startPeriod": 20, "limit": 0},
            {"startPeriod": 10 if kind == "unordered" else 20, "limit": 0},
        ]
    else:
        schedule["chargingSchedulePeriod"][0]["limit"] = {
            "nan": float("nan"),
            "infinite": float("inf"),
            "boolean_limit": False,
        }[kind]
    monkeypatch.setattr(worker, "command", AsyncMock(return_value=("Accepted", reply)))
    assert not await worker.verify_limit(phase_device(1), uuid4(), 1, 0)


@pytest.mark.parametrize(
    "start",
    [
        None,
        "invalid",
        "2026-01-01T00:00:00",
        "2000-01-01T00:00:00Z",
        "2999-01-01T00:00:00Z",
    ],
)
async def test_composite_must_describe_current_aware_schedule(monkeypatch, start):
    reply = {
        "connectorId": 1,
        "scheduleStart": start,
        "chargingSchedule": {
            "duration": 60,
            "chargingRateUnit": "W",
            "chargingSchedulePeriod": [{"startPeriod": 0, "limit": 0}],
        },
    }
    monkeypatch.setattr(worker, "command", AsyncMock(return_value=("Accepted", reply)))
    assert not await worker.verify_limit(phase_device(1), uuid4(), 1, 0)


@pytest.mark.parametrize("status", [[], {}, True, 1, None])
async def test_malformed_wire_status_is_protocol_error(status):
    from src.modules.ocpp.frames import Frame

    connection = SimpleNamespace(
        call=AsyncMock(return_value=Frame(3, "reply", {"status": status}))
    )
    assert await worker.wire(connection, "SetChargingProfile", {}, uuid4()) == (
        "ProtocolError",
        {},
    )


@pytest.mark.parametrize(
    "error,expected",
    [
        (TimeoutError(), "Timeout"),
        (ConnectionError(), "Disconnected"),
        (RuntimeError(), "Disconnected"),
    ],
)
async def test_wire_connection_failure_classification(error, expected):
    connection = SimpleNamespace(call=AsyncMock(side_effect=error))
    assert await worker.wire(connection, "SetChargingProfile", {}, uuid4()) == (
        expected,
        {},
    )


@pytest.mark.parametrize(
    "outcome", ["Rejected", "Timeout", "Disconnected", "ProtocolError"]
)
@pytest.mark.parametrize(
    "failed_action", ["SetChargingProfile", "GetCompositeSchedule"]
)
async def test_failed_reduction_never_lends_budget_or_increases_other_cars(
    fleet, monkeypatch, outcome, failed_action
):
    factory, station, charger, ids, _, _ = fleet
    watts, trace, _ = device_wire(monkeypatch, charger)
    await configure(fleet)
    await run_plan(factory, station)
    await sessions(fleet)
    await run_plan(factory, station)
    original = worker.wire

    async def fail(connection, action, payload, request_id):
        if action == failed_action and payload.get("connectorId") == 1:
            return outcome, {}
        return await original(connection, action, payload, request_id)

    monkeypatch.setattr(worker, "wire", fail)
    async with factory() as db, db.begin():
        (await db.get(Connector, ids[0])).raw_ocpp_status = "SuspendedEV"
    trace.clear()
    await run_plan(factory, station)
    assert watts[2] == watts[3] == 10000 and sum(watts.values()) <= 30000
    assert not any(
        p["csChargingProfiles"]["chargingSchedule"]["chargingSchedulePeriod"][0][
            "limit"
        ]
        > 10000
        for a, p in trace
        if a == "SetChargingProfile"
    )
    async with factory() as db:
        cap = await db.get(ConnectorPower, ids[0])
        assert cap.confirmed_w == cap.reserved_w == 10000
        assert (await db.get(StationPower, station.id)).state == "degraded"
        assert not await power_start_allowed(db, station.id)
    monkeypatch.setattr(worker, "wire", original)
    await run_plan(factory, station)
    assert watts == {1: 0, 2: 15000, 3: 15000}


@pytest.mark.parametrize(
    "values",
    [
        [{"key": [], "value": "x"}],
        [{"key": "x", "value": {}}],
        [{"key": "x", "value": "a"}, {"key": "x", "value": "b"}],
        [None],
    ],
)
async def test_malformed_capabilities_fail_closed_without_killing_worker(
    monkeypatch, values
):
    monkeypatch.setattr(
        worker,
        "command",
        AsyncMock(return_value=("Accepted", {"configurationKey": values})),
    )
    assert not await worker.capabilities(phase_device(1), uuid4(), 1)


async def test_evse_suspended_vehicle_can_receive_power_from_zero_baseline(
    fleet, monkeypatch
):
    factory, station, charger, ids, _, _ = fleet
    state, _, _ = device_wire(monkeypatch, charger)
    await configure(fleet)
    await run_plan(factory, station)
    await sessions(fleet)
    async with factory() as db, db.begin():
        (await db.get(Connector, ids[0])).raw_ocpp_status = "SuspendedEVSE"
    await run_plan(factory, station)
    assert list(state.values()) == [10000] * 3


async def test_unauthorized_session_gets_no_power_and_stop_retry_is_durable(
    fleet, monkeypatch
):
    factory, station, charger, _, _, _ = fleet
    state, _, _ = device_wire(monkeypatch, charger)
    await configure(fleet)
    await run_plan(factory, station)
    await sessions(fleet)
    async with factory() as db, db.begin():
        transaction = await db.scalar(
            select(ChargingSession).order_by(ChargingSession.id)
        )
        transaction.authorization_status = "Invalid"
        tx_id = transaction.id
    await run_plan(factory, station)
    await run_plan(factory, station)
    assert sum(state.values()) == 0
    async with factory() as db:
        assert (
            await db.get(StationPower, station.id)
        ).issue == "power_unauthorized_session"
        assert not await power_start_allowed(db, station.id)
        assert (await db.get(ChargingSession, tx_id)).ended_at is None
        stops = list(
            await db.scalars(
                select(PowerCommand).where(
                    PowerCommand.action == "RemoteStopTransaction"
                )
            )
        )
        assert len(stops) == 1 and stops[0].payload == {"transactionId": tx_id}


async def test_cancelled_worker_reuses_committed_profile_intent(fleet, monkeypatch):
    factory, station, charger, _, _, _ = fleet
    state, _, _ = device_wire(monkeypatch, charger)
    await configure(fleet)
    await run_plan(factory, station)
    await sessions(fleet)
    original = worker.wire
    applied = asyncio.Event()
    sent = []

    async def lose_ack(connection, action, payload, request_id):
        result = await original(connection, action, payload, request_id)
        if action == "SetChargingProfile":
            sent.append(request_id)
            if len(sent) == 1:
                applied.set()
                await asyncio.Future()
        return result

    monkeypatch.setattr(worker, "wire", lose_ack)
    task = asyncio.create_task(run_plan(factory, station))
    await asyncio.wait_for(applied.wait(), 5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    async with factory() as db:
        cap = await db.scalar(
            select(ConnectorPower).where(ConnectorPower.pending_command_id == sent[0])
        )
        assert cap is not None and cap.reserved_w == 10000 and cap.confirmed_w == 0
        assert (await db.get(PowerCommand, sent[0])).status == "Pending"
    await run_plan(factory, station)
    assert sent[1] == sent[0] and sum(state.values()) == 30000


@pytest.mark.parametrize("during", ["SetChargingProfile", "ClearChargingProfile"])
async def test_stale_disable_cannot_override_new_enable_request(
    fleet, monkeypatch, during
):
    factory, station, charger, _, scope, evidence = fleet
    _, trace, _ = device_wire(monkeypatch, charger)
    await configure(fleet)
    await run_plan(factory, station)
    async with factory() as db, db.begin():
        version = (await db.get(StationPower, station.id)).version
        await change_control(db, station.id, version, False, scope, evidence)
    original = worker.wire
    changed = False

    async def reenable(connection, action, payload, request_id):
        nonlocal changed
        result = await original(connection, action, payload, request_id)
        if action == during and not changed:
            changed = True
            async with factory() as db, db.begin():
                config = await db.get(StationPower, station.id)
                await change_control(
                    db, station.id, config.version, True, scope, evidence
                )
        return result

    monkeypatch.setattr(worker, "wire", reenable)
    trace.clear()
    await run_plan(factory, station)
    async with factory() as db:
        config = await db.get(StationPower, station.id)
        assert config.enabled and config.target_enabled and config.state == "bootstrap"
        if during == "ClearChargingProfile":
            assert all(
                c.baseline_boot_at is None
                for c in await db.scalars(select(ConnectorPower))
            )
        else:
            assert not any(action == "ClearChargingProfile" for action, _ in trace)
        assert not await power_start_allowed(db, station.id)
    await run_plan(factory, station)
    async with factory() as db:
        assert (await db.get(StationPower, station.id)).state == "ready"
        assert await power_start_allowed(db, station.id)


async def test_phase_bounds_concurrency_and_serializes_each_charger(monkeypatch):
    inputs = [phase_device(index) for index in range(1, 11)]
    inputs.append(replace(inputs[0], connector_id=UUID(int=11), number=2))
    active = set()
    peak = 0

    async def set_limit(device, *args):
        nonlocal peak
        assert device.charge_point_id not in active
        active.add(device.charge_point_id)
        peak = max(peak, len(active))
        await asyncio.sleep(0.02)
        active.remove(device.charge_point_id)
        return True

    monkeypatch.setattr(worker, "set_limit", set_limit)
    assert await worker.apply_phase(
        inputs, {d.connector_id: 1000 for d in inputs}, uuid4(), 1
    )
    assert peak == 5 and not active


async def test_phase_failure_waits_for_siblings_and_does_not_start_increases(
    monkeypatch,
):
    inputs = [phase_device(index) for index in range(1, 4)]
    finished = []
    degraded = []

    async def set_limit(device, *args):
        await asyncio.sleep(0.01 if device == inputs[0] else 0.05)
        finished.append(device.connector_id)
        return device != inputs[0]

    async def degrade(station, generation, issue, device):
        assert len(finished) == 3
        degraded.append(device.connector_id)

    monkeypatch.setattr(worker, "set_limit", set_limit)
    monkeypatch.setattr(worker, "degrade", degrade)
    assert not await worker.apply_phase(
        inputs, {d.connector_id: 0 for d in inputs}, uuid4(), 1
    )
    assert degraded == [inputs[0].connector_id]


async def test_phase_exception_drains_sibling_writes_before_releasing_lock(monkeypatch):
    inputs = [phase_device(index) for index in range(1, 3)]
    finished = []

    async def set_limit(device, *args):
        if device == inputs[0]:
            raise OSError("disconnected")
        await asyncio.sleep(0.05)
        finished.append(device.connector_id)
        return True

    monkeypatch.setattr(worker, "set_limit", set_limit)
    with pytest.raises(OSError, match="disconnected"):
        await worker.apply_phase(
            inputs, {d.connector_id: 0 for d in inputs}, uuid4(), 1
        )
    assert finished == [inputs[1].connector_id]
