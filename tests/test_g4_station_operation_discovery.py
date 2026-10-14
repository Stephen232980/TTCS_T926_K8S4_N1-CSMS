"""G4 admission transitions and public availability using PostgreSQL/OCPP."""

import asyncio
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from time import perf_counter
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from src.entrypoints.http import app
from src.modules.charging import driver as driver_service
from src.modules.charging.driver_models import DriverStartRequest
from src.modules.charging.models import ChargingSession
from src.modules.identity.authorization import CurrentActor
from src.modules.identity.dependencies import get_current_actor
from src.modules.identity.models import User
from src.modules.pricing.models import Tariff, TariffBand
from src.modules.stations.discovery import summaries
from src.modules.stations.models import ChargePoint, Connector, Station
from src.platform.audit.models import AuditLog
from tests.test_charging_sessions import call, meter_payload, setup, start
from tests.test_flat_tariff_api import api_db, committed_tariff_db  # noqa: F401


@pytest.fixture
async def fleet(api_db, monkeypatch):  # noqa: F811
    now = datetime.now(UTC)
    async with api_db() as db, db.begin():
        station, point, connector, driver, _card, connection, tag = await setup(db)
        point.status = "online"
        point.last_seen_at = point.last_boot_at = now
        point.heartbeat_interval_seconds = 60
        connector.connector_type, connector.current_type = "Type 2", "AC"
        connector.max_power_kw = 22
        tariff = Tariff(
            station_id=station.id,
            effective_from=now.astimezone(ZoneInfo(station.timezone)).date(),
            idle_rate_vnd_per_minute=1000,
            grace_minutes=5,
        )
        db.add(tariff)
        await db.flush()
        db.add(
            TariffBand(
                tariff_id=tariff.id,
                start_min=0,
                end_min=1440,
                energy_rate_vnd_per_kwh=2500,
                label="Cả ngày",
            )
        )
    monkeypatch.setattr(driver_service, "SessionFactory", api_db)
    app.dependency_overrides[get_current_actor] = lambda: CurrentActor(
        station.owner_id, frozenset({"station_owner"})
    )
    yield api_db, station, point, connector, driver, connection, tag, now
    app.dependency_overrides.pop(get_current_actor, None)


def client():
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def operate(station, status, version=1, reason="Bảo trì"):
    async with client() as http:
        return await http.patch(
            f"/api/v1/owner/stations/{station.id}/operation",
            json={
                "status": status,
                "expected_version": version,
                "reason": reason,
            },
        )


async def test_suspend_resume_retry_audit_and_discovery(fleet):
    factory, station, _, _, _, _, _, _ = fleet
    response = await operate(station, "suspended")
    assert response.status_code == 200
    assert response.json()["status_version"] == 2
    assert (await operate(station, "suspended")).status_code == 200
    async with factory() as db:
        assert (
            await db.scalar(
                select(func.count())
                .select_from(AuditLog)
                .where(AuditLog.action == "station.operation_changed")
            )
            == 1
        )
    app.dependency_overrides[get_current_actor] = lambda: CurrentActor(
        uuid4(), frozenset({"driver"})
    )
    async with client() as http:
        assert (await http.get("/api/v1/driver/stations")).json()["total"] == 0
    app.dependency_overrides[get_current_actor] = lambda: CurrentActor(
        station.owner_id, frozenset({"station_owner"})
    )
    assert (await operate(station, "active", version=2)).status_code == 200
    assert (await operate(station, "suspended", version=1)).status_code == 409


@pytest.mark.parametrize("roles", [{"driver"}, {"operator"}, {"admin"}, {"accountant"}])
async def test_operation_role_denied(fleet, roles):
    _, station, *_ = fleet
    app.dependency_overrides[get_current_actor] = lambda: CurrentActor(
        station.owner_id, frozenset(roles)
    )
    assert (await operate(station, "suspended")).status_code == 403


async def test_operation_ownership_blocked_and_reason(fleet):
    factory, station, *_ = fleet
    app.dependency_overrides[get_current_actor] = lambda: CurrentActor(
        uuid4(), frozenset({"station_owner"})
    )
    assert (await operate(station, "suspended")).status_code == 403
    app.dependency_overrides[get_current_actor] = lambda: CurrentActor(
        station.owner_id, frozenset({"station_owner"})
    )
    assert (await operate(station, "suspended", reason="  ")).status_code == 422
    async with factory() as db, db.begin():
        (await db.get(Station, station.id)).status = "blocked"
    assert (await operate(station, "active")).json()[
        "detail"
    ] == "station_admin_blocked"


async def test_activate_requires_connector_and_full_effective_tariff(fleet):
    factory, station, _, connector, *_ = fleet
    async with factory() as db, db.begin():
        (await db.get(Station, station.id)).status = "inactive"
        (await db.get(Connector, connector.id)).archived_at = datetime.now(UTC)
    assert (await operate(station, "active")).json()[
        "detail"
    ] == "station_connector_required"
    async with factory() as db, db.begin():
        (await db.get(Connector, connector.id)).archived_at = None
        band = await db.scalar(select(TariffBand))
        band.start_min = 1
    assert (await operate(station, "active")).json()[
        "detail"
    ] == "station_tariff_required"


async def test_concurrent_opposite_intents_have_one_winner(fleet):
    factory, station, *_ = fleet
    assert (await operate(station, "suspended")).status_code == 200
    # Both resume requests share the revision; exact replay does not duplicate audit.
    responses = await asyncio.gather(
        *(operate(station, "active", version=2) for _ in range(8))
    )
    assert all(response.status_code == 200 for response in responses)
    async with factory() as db:
        stored = await db.get(Station, station.id)
        assert stored.status == "active" and stored.status_version == 3
        assert (
            await db.scalar(
                select(func.count())
                .select_from(AuditLog)
                .where(AuditLog.action == "station.operation_changed")
            )
            == 2
        )


async def test_open_socket_after_suspend_blocks_all_new_starts_preserves_session(fleet):
    factory, station, _point, connector, driver, conn, tag, now = fleet
    async with factory() as db, db.begin():
        first = await start(db, conn, tag, now)
        session_id = first.payload["transactionId"]
        assert first.payload["idTagInfo"]["status"] == "Accepted"
    assert (await operate(station, "suspended")).status_code == 200
    # Intentionally stale in-memory station status must not override DB admission.
    assert conn.station_status == "active"
    async with factory() as db, db.begin():
        assert (await call(db, conn, "Authorize", {"idTag": tag})).payload["idTagInfo"][
            "status"
        ] == "Blocked"
        refused = await start(db, conn, tag, now + timedelta(seconds=1))
        assert refused.payload == {
            "transactionId": 0,
            "idTagInfo": {"status": "Blocked"},
        }
        assert await db.scalar(select(func.count()).select_from(ChargingSession)) == 1
        active = await db.get(ChargingSession, session_id)
        assert active.ended_at is None
        await call(
            db,
            conn,
            "MeterValues",
            meter_payload(session_id, now + timedelta(seconds=2), 2000),
        )
        await call(
            db,
            conn,
            "StopTransaction",
            {
                "transactionId": session_id,
                "meterStop": 2000,
                "timestamp": (now + timedelta(seconds=3)).isoformat(),
                "reason": "EVDisconnected",
            },
        )
        await db.refresh(active)
        assert active.ended_at is not None
        assert active.energy_kwh == 1
    with pytest.raises(HTTPException) as error:
        await driver_service.remote_start(driver.id, uuid4(), connector.id)
    assert error.value.status_code == 409
    conn.websocket.send_text.assert_not_awaited()
    # After resume, the same socket authorizes again without reconnecting.
    assert (await operate(station, "active", version=2)).status_code == 200
    async with factory() as db, db.begin():
        assert (await call(db, conn, "Authorize", {"idTag": tag})).payload["idTagInfo"][
            "status"
        ] == "Accepted"


async def test_suspend_wins_station_lock_before_start(fleet):
    factory, station, _, _, _, conn, tag, now = fleet
    async with factory() as held, held.begin():
        stored = await held.scalar(
            select(Station).where(Station.id == station.id).with_for_update()
        )
        stored.status = "suspended"

        async def attempt():
            async with factory() as db, db.begin():
                return await start(db, conn, tag, now)

        task = asyncio.create_task(attempt())
        await asyncio.sleep(0.15)
        assert not task.done()
    reply = await asyncio.wait_for(task, 5)
    assert reply.payload["transactionId"] == 0


async def test_late_start_persists_station_rejection_for_pending_driver(fleet):
    factory, station, point, connector, driver, conn, _, now = fleet
    key = uuid4()
    async with factory() as db, db.begin():
        raw_tag = await driver_service.virtual_tag(db, await db.get(User, driver.id))
        db.add(
            DriverStartRequest(
                id=key,
                driver_id=driver.id,
                connector_id=connector.id,
                charge_point_id=point.id,
                created_at=now,
                status="Accepted",
                reply_status="Accepted",
                lease_until=now + timedelta(minutes=1),
            )
        )
    assert (await operate(station, "suspended")).status_code == 200
    async with factory() as db, db.begin():
        assert (await start(db, conn, raw_tag, now)).payload["transactionId"] == 0
    async with factory() as db:
        request = await db.get(DriverStartRequest, key)
        assert (
            request.status == "Rejected"
            and request.rejection_reason == "station_unavailable"
        )


@pytest.mark.parametrize(
    "state",
    [
        "offline",
        "expired",
        "future",
        "no_boot",
        "Reserved",
        "Finishing",
        "Faulted",
        "occupied",
        "pending",
    ],
)
async def test_discovery_excludes_unavailable_connectors(fleet, state):
    factory, station, point, connector, driver, _, _, now = fleet
    async with factory() as db, db.begin():
        point = await db.get(ChargePoint, point.id)
        connector = await db.get(Connector, connector.id)
        if state == "offline":
            point.status = "offline"
        elif state == "expired":
            point.last_seen_at = now - timedelta(seconds=121)
        elif state == "future":
            point.last_seen_at = now + timedelta(seconds=1)
        elif state == "no_boot":
            point.last_boot_at = None
        elif state in {"Reserved", "Finishing", "Faulted"}:
            connector.status = state
        elif state == "occupied":
            db.add(
                ChargingSession(
                    charge_point_id=point.id,
                    connector_id=connector.id,
                    driver_id=driver.id,
                    tag_tail="ABCD",
                    authorization_status="Accepted",
                    started_at=now - timedelta(minutes=1),
                    ended_at=now,
                    meter_start_wh=0,
                    billing_lifecycle_version=1,
                    connector_released_at=None,
                )
            )
        elif state == "pending":
            db.add(
                DriverStartRequest(
                    id=uuid4(),
                    driver_id=driver.id,
                    connector_id=connector.id,
                    charge_point_id=point.id,
                    created_at=now,
                    status="Accepted",
                    reply_status="Accepted",
                    lease_until=now + timedelta(minutes=1),
                )
            )
        await db.flush()
        projection = (await summaries(db, [station], now))[station.id]
        assert projection["total_connectors"] == 1
        assert projection["available_connectors"] == 0


async def test_discovery_tariff_midnight_timezone_and_no_private_fields(fleet):
    factory, station, _, _, _, _, _, _now = fleet
    boundary = datetime(2027, 1, 1, 17, 0, tzinfo=UTC)
    async with factory() as db, db.begin():
        db.add(
            Tariff(
                station_id=station.id,
                effective_from=boundary.astimezone(ZoneInfo(station.timezone)).date(),
                idle_rate_vnd_per_minute=0,
                grace_minutes=10,
            )
        )
        await db.flush()
        latest = await db.scalar(select(Tariff).order_by(Tariff.effective_from.desc()))
        db.add(
            TariffBand(
                tariff_id=latest.id,
                start_min=0,
                end_min=1440,
                energy_rate_vnd_per_kwh=3500,
                label="Mới",
            )
        )
        await db.flush()
        assert (await summaries(db, [station], boundary - timedelta(seconds=1)))[
            station.id
        ]["energy_rate_vnd_per_kwh"] == 2500
        assert (await summaries(db, [station], boundary))[station.id][
            "energy_rate_vnd_per_kwh"
        ] == 3500
    app.dependency_overrides[get_current_actor] = lambda: CurrentActor(
        uuid4(), frozenset({"driver"})
    )
    async with client() as http:
        data = (await http.get("/api/v1/driver/stations")).json()
    assert data["items"][0]["available_connectors"] == 1
    assert (
        not {"owner_id", "email", "tag_hash", "status_version"}
        & data["items"][0].keys()
    )


async def test_bounded_discovery_500_stations_under_two_seconds(fleet):
    factory, station, *_ = fleet
    async with factory() as db, db.begin():
        stations = [
            Station(
                owner_id=station.owner_id,
                name=f"Scale {i:03}",
                address="Test",
                latitude=10.7,
                longitude=106.7,
                status="active",
            )
            for i in range(500)
        ]
        db.add_all(stations)
        await db.flush()
        now = datetime.now(UTC)
        points = [
            ChargePoint(
                station_id=stations[0].id,
                code=f"scale-{uuid4()}",
                status="online",
                last_seen_at=now,
                last_boot_at=now,
            )
            for _ in range(50)
        ]
        db.add_all(points)
        await db.flush()
        db.add_all(
            [
                Connector(
                    charge_point_id=point.id,
                    connector_number=1,
                    status="Available",
                    connector_type="Type 2",
                    max_power_kw=22,
                )
                for point in points
            ]
        )
    app.dependency_overrides[get_current_actor] = lambda: CurrentActor(
        uuid4(), frozenset({"driver"})
    )
    async with client() as http:
        broad = (await http.get("/api/v1/driver/stations")).json()
        assert broad["search_too_broad"] and broad["items"] == []
        durations = []
        for _ in range(5):
            begin = perf_counter()
            data = (
                await http.get("/api/v1/driver/stations?search=Scale&page_size=100")
            ).json()
            durations.append(perf_counter() - begin)
            assert data["total"] == 500 and len(data["items"]) == 100
            assert data["items"][0]["available_connectors"] == 50
        assert max(durations) < 2
        print(f"G4 500 stations / 50 chargers max response: {max(durations):.3f}s")


async def test_operation_migration_roundtrip_preserves_station(fleet):
    factory, station, *_ = fleet
    url = factory.kw["bind"].url.render_as_string(hide_password=False)
    for target in ("b220022a2026", "head"):
        result = await asyncio.to_thread(
            subprocess.run,
            [
                sys.executable,
                "-m",
                "alembic",
                "downgrade" if target != "head" else "upgrade",
                target,
            ],
            env=os.environ | {"DATABASE_URL": url},
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
    async with factory() as db:
        stored = await db.get(Station, station.id)
        assert stored.name == station.name and stored.status_version == 1
