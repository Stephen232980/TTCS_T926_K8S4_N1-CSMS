"""G1 budgets: source-independent answers, PostgreSQL races and device failures."""

import asyncio
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
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
from src.modules.power.service import change_control, power_start_allowed, save_settings
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
                "chargingSchedule": {
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
