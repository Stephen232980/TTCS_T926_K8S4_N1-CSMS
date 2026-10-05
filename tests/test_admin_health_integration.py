from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.schema import CreateSchema, DropSchema

from src.config import settings
from src.entrypoints.http import app
from src.modules.charging.models import ChargingSession
from src.modules.identity.authorization import CurrentActor
from src.modules.identity.dependencies import get_current_actor
from src.modules.identity.models import AccountAudit, User
from src.modules.ocpp import admin_health_service
from src.modules.ocpp.admin_health_models import OcppTelemetryBucket, SystemHealthSample
from src.modules.ocpp.admin_health_router import health_now
from src.modules.ocpp.admin_health_service import collect_health
from src.modules.ocpp.monitoring import StatusPayload, report_status
from src.modules.ocpp.telemetry import TelemetryBuffer
from src.modules.stations.models import ChargePoint, Connector, Station
from src.platform.database.base import Base
from src.platform.database.session import get_db_session

NOW = datetime(2038, 5, 1, 12, 0, tzinfo=UTC)
HEALTH = "/api/v1/admin/system-health"


@pytest_asyncio.fixture
async def health_db(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[AsyncSession]:
    # An isolated schema protects existing demo health/history from retention tests.
    schema = f"health_test_{uuid4().hex}"
    engine = create_async_engine(
        settings.database_url,
        execution_options={"schema_translate_map": {None: schema}},
    )
    async with engine.begin() as connection:
        await connection.execute(CreateSchema(schema))
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(admin_health_service, "SessionFactory", factory)
    try:
        async with factory() as db:

            async def override_db() -> AsyncIterator[AsyncSession]:
                yield db

            app.dependency_overrides[get_db_session] = override_db
            app.dependency_overrides[health_now] = lambda: NOW
            app.dependency_overrides[get_current_actor] = lambda: CurrentActor(
                uuid4(), frozenset({"admin"})
            )
            yield db
            await db.rollback()
    finally:
        app.dependency_overrides.clear()
        async with engine.begin() as connection:
            await connection.execute(DropSchema(schema, cascade=True))
        await engine.dispose()


async def make_charger(
    db: AsyncSession,
    *,
    status: str = "online",
    station_status: str = "active",
    seen: datetime = NOW,
    raw: str = "Charging",
    ended: bool = False,
) -> ChargePoint:
    owner = User(email=f"{uuid4().hex}@example.com", password_hash="not-a-login-hash")
    db.add(owner)
    await db.flush()
    station = Station(
        owner_id=owner.id,
        name="Test",
        address="Test",
        latitude=Decimal(10),
        longitude=Decimal(106),
        status=station_status,
    )
    db.add(station)
    await db.flush()
    charger = ChargePoint(
        station_id=station.id,
        code=uuid4().hex,
        status=status,
        last_boot_at=NOW - timedelta(hours=1),
        last_seen_at=seen,
        heartbeat_interval_seconds=60,
    )
    db.add(charger)
    await db.flush()
    connector = Connector(
        charge_point_id=charger.id,
        connector_number=1,
        status=raw,
        raw_ocpp_status=raw,
    )
    db.add(connector)
    await db.flush()
    db.add(
        ChargingSession(
            charge_point_id=charger.id,
            connector_id=connector.id,
            driver_id=None,
            tag_tail="TEST",
            authorization_status="Accepted",
            started_at=NOW - timedelta(minutes=20),
            ended_at=NOW if ended else None,
            meter_start_wh=Decimal(0),
            review_reasons=[],
        )
    )
    await db.commit()
    return charger


@pytest.mark.asyncio
async def test_running_count_follows_status_notification_storage(
    health_db: AsyncSession,
) -> None:
    charger = await make_charger(health_db, raw="Available")
    buffer = TelemetryBuffer(started_at=NOW - timedelta(minutes=6))
    for offset, (status, expected) in enumerate(
        [("Available", 0), ("Charging", 1), ("SuspendedEV", 0), ("Charging", 1)]
    ):
        await report_status(
            health_db,
            charger,
            StatusPayload(connectorId=1, status=status, errorCode="NoError"),
        )
        await health_db.commit()
        instant = NOW + timedelta(seconds=offset * 30)
        await collect_health(now=instant, buffer=buffer)
        sample = await health_db.scalar(
            select(SystemHealthSample)
            .where(SystemHealthSample.collected_at == instant)
            .execution_options(populate_existing=True)
        )
        assert sample is not None
        assert sample.running_sessions == expected


@pytest.mark.asyncio
async def test_real_counts_running_is_not_all_open_sessions(
    health_db: AsyncSession,
) -> None:
    await make_charger(health_db)
    await make_charger(health_db, raw="SuspendedEV")
    await make_charger(health_db, station_status="blocked")
    await make_charger(health_db, seen=NOW - timedelta(seconds=121))
    await make_charger(health_db, ended=True)
    archived = await make_charger(health_db)
    archived.archived_at = NOW
    await health_db.commit()
    buffer = TelemetryBuffer(started_at=NOW - timedelta(minutes=6))
    buffer.record(error=True, latency_ms=100, at=NOW - timedelta(seconds=40))
    buffer.record(error=False, latency_ms=300, at=NOW - timedelta(seconds=50))
    buffer.record(error=True, latency_ms=9999, at=NOW - timedelta(minutes=6))
    await collect_health(now=NOW, buffer=buffer)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(HEALTH)
        assert response.status_code == 200, response.text
        metrics = response.json()["snapshot"]["metrics"]
        assert metrics["registered_charge_points"] == 5
        assert metrics["online_charge_points"] == 3
        assert metrics["running_sessions"] == 1
        assert metrics["error_messages_5m"] == 1
        assert metrics["response_latency_ms"] == 200
        assert metrics["response_count_5m"] == 2
        assert metrics["window_complete"] is True
        assert response.headers["cache-control"] == "no-store"
    # Replay/collection in the same time bucket neither doubles counters nor creates samples.
    await collect_health(now=NOW, buffer=buffer)
    assert len(list(await health_db.scalars(select(SystemHealthSample)))) == 1
    bucket = await health_db.scalar(
        select(OcppTelemetryBucket).where(
            OcppTelemetryBucket.timestamp == NOW - timedelta(seconds=60)
        )
    )
    assert bucket and bucket.response_count == 2


@pytest.mark.asyncio
async def test_no_data_warmup_and_stale_history_keep_gaps(
    health_db: AsyncSession,
) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        empty = (await client.get(HEALTH)).json()
        assert empty["status"] == "no_data" and empty["snapshot"] is None
        points = (await client.get(f"{HEALTH}/history")).json()["points"]
        assert len(points) == 25 and all(p["metrics"] is None for p in points)
        buffer = TelemetryBuffer(started_at=NOW - timedelta(seconds=5))
        await collect_health(now=NOW, buffer=buffer)
        data = (await client.get(HEALTH)).json()["snapshot"]["metrics"]
        assert data["error_messages_5m"] is None
        assert data["window_complete"] is False
        assert data["response_latency_ms"] is None
        assert data["online_charge_points"] == 0
        app.dependency_overrides[health_now] = lambda: NOW + timedelta(seconds=91)
        assert (await client.get(HEALTH)).json()["status"] == "stale"
        history = (
            await client.get(f"{HEALTH}/history", params={"resolution_seconds": 30})
        ).json()
        assert len(history["points"]) == 2881
        assert sum(p["metrics"] is not None for p in history["points"]) == 1
        assert (
            await client.get(f"{HEALTH}/history", params={"resolution_seconds": 120})
        ).status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["station_owner", "operator", "driver", "accountant"])
async def test_admin_only_health_and_account_audit(
    health_db: AsyncSession, role: str
) -> None:
    app.dependency_overrides[get_current_actor] = lambda: CurrentActor(
        uuid4(), frozenset({role})
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        for url in [HEALTH, f"{HEALTH}/history", "/api/v1/admin/account-audit"]:
            denied = await client.get(url)
            assert denied.status_code == 403
        app.dependency_overrides.pop(get_current_actor)
        assert (await client.get(HEALTH)).status_code == 401


@pytest.mark.asyncio
async def test_account_audit_read_filters_and_immutable_http(
    health_db: AsyncSession,
) -> None:
    actor = User(email="actor@example.com", password_hash="unused")
    target = User(email="target@example.com", password_hash="unused")
    health_db.add_all([actor, target])
    await health_db.flush()
    after = {"email": target.email, "roles": ["driver"], "status": "active"}
    health_db.add_all(
        [
            AccountAudit(
                actor_id=actor.id,
                target_id=target.id,
                action="account_created",
                before_state=None,
                after_state=after,
                created_at=NOW,
            ),
            AccountAudit(
                actor_id=actor.id,
                target_id=target.id,
                action="account_updated",
                before_state=after,
                after_state={**after, "status": "suspended"},
                created_at=NOW + timedelta(seconds=1),
            ),
        ]
    )
    await health_db.commit()
    url = "/api/v1/admin/account-audit"
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            url, params={"actor_email": "ACTOR@EXAMPLE.COM", "page_size": 1}
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["total"] == 2 and data["total_pages"] == 2
        assert data["items"][0]["action"] == "account_updated"
        assert "password" not in response.text
        assert (
            await client.get(
                url, params={"action": "account_created", "target_id": str(target.id)}
            )
        ).json()["total"] == 1
        assert (
            await client.get(
                url, params={"from_at": (NOW + timedelta(seconds=1)).isoformat()}
            )
        ).json()["total"] == 1
        assert (
            await client.get(
                url,
                params={
                    "from_at": (NOW + timedelta(hours=1)).isoformat(),
                    "to_at": NOW.isoformat(),
                },
            )
        ).status_code == 422
        assert (await client.patch(url, json={})).status_code == 405


@pytest.mark.asyncio
async def test_collection_retry_does_not_lose_dirty_counters(
    health_db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    buffer = TelemetryBuffer(started_at=NOW - timedelta(minutes=6))
    buffer.record(error=True, latency_ms=23, at=NOW - timedelta(seconds=10))
    original = admin_health_service.capture_sample

    async def fail(db: AsyncSession, now: datetime) -> None:
        raise RuntimeError("test rollback")

    monkeypatch.setattr(admin_health_service, "capture_sample", fail)
    with pytest.raises(RuntimeError, match="test rollback"):
        await collect_health(now=NOW, buffer=buffer)
    assert buffer.snapshot(NOW)
    monkeypatch.setattr(admin_health_service, "capture_sample", original)
    await collect_health(now=NOW, buffer=buffer)
    saved = await health_db.scalar(select(SystemHealthSample))
    assert saved and saved.error_messages_5m == 1 and saved.response_latency_ms == 23
