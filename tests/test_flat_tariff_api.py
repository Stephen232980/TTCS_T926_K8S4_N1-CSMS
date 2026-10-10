import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.entrypoints.http import app
from src.modules.identity.authorization import CurrentActor
from src.modules.identity.dependencies import get_current_actor
from src.modules.pricing.models import Tariff, TariffBand
from src.platform.database.session import get_db_session
from tests.test_effective_tariffs import committed_tariff_db  # noqa: F401
from tests.test_tariff_schema import make_station


def payload(day):
    return {
        "effective_from": day.isoformat(),
        "energy_rate_vnd_per_kwh": 2500,
        "idle_rate_vnd_per_minute": 1000,
        "grace_minutes": 5,
    }


@pytest.fixture
def client_factory():
    async def request(station_id, body, actor=None):
        if actor is not None:
            app.dependency_overrides[get_current_actor] = lambda: actor
        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                return await client.post(
                    f"/api/v1/owner/stations/{station_id}/tariffs", json=body
                )
        finally:
            app.dependency_overrides.pop(get_current_actor, None)

    return request


async def test_anonymous_denied(client_factory):
    response = await client_factory(uuid4(), payload(datetime.now(UTC).date()))
    assert response.status_code == 401


@pytest.mark.parametrize("roles", [{"admin"}, {"operator"}, {"driver"}, {"accountant"}])
async def test_non_owner_roles_denied(client_factory, roles):
    response = await client_factory(
        uuid4(),
        payload(datetime.now(UTC).date()),
        CurrentActor(uuid4(), frozenset(roles)),
    )
    assert response.status_code == 403


@pytest.mark.parametrize(
    "field,value",
    [
        ("energy_rate_vnd_per_kwh", -1),
        ("energy_rate_vnd_per_kwh", 2500.5),
        ("energy_rate_vnd_per_kwh", True),
        ("energy_rate_vnd_per_kwh", "2500"),
        ("energy_rate_vnd_per_kwh", 2**63),
        ("idle_rate_vnd_per_minute", -1),
        ("idle_rate_vnd_per_minute", 1.5),
        ("grace_minutes", -1),
        ("grace_minutes", 1.5),
        ("grace_minutes", 2**31),
        ("effective_from", "2026-10-08T00:00:00Z"),
        ("effective_from", 1791417600),
        ("label", ""),
        ("label", "x" * 101),
        ("owner_id", str(uuid4())),
    ],
)
async def test_invalid_body_names_field(client_factory, field, value):
    body = payload(datetime.now(UTC).date())
    body[field] = value
    response = await client_factory(
        uuid4(), body, CurrentActor(uuid4(), frozenset({"station_owner"}))
    )
    assert response.status_code == 422
    assert any(error["loc"] == ["body", field] for error in response.json()["detail"])


@pytest.fixture
async def api_db(committed_tariff_db):  # noqa: F811 -- imported pytest fixture
    factory = committed_tariff_db

    async def database():
        async with factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db_session] = database
    try:
        yield factory
    finally:
        app.dependency_overrides.pop(get_db_session, None)


async def setup_station(factory, zone="Asia/Ho_Chi_Minh"):
    async with factory() as session:
        station = await make_station(session)
        station.timezone = zone
        await session.commit()
        return station, CurrentActor(station.owner_id, frozenset({"station_owner"}))


async def test_t62_context_empty_current_and_future_preserves_rates(
    api_db, client_factory
):
    station, actor = await setup_station(api_db, "Pacific/Kiritimati")
    path = f"/api/v1/owner/stations/{station.id}/tariffs/context"

    async def read():
        app.dependency_overrides[get_current_actor] = lambda: actor
        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                return await client.get(path)
        finally:
            app.dependency_overrides.pop(get_current_actor, None)

    empty = await read()
    assert empty.status_code == 200
    assert empty.headers["cache-control"] == "no-store"
    today = datetime.now(ZoneInfo(station.timezone)).date()
    assert empty.json()["today"] == today.isoformat()
    assert empty.json()["has_versions"] is False
    first = payload(today)
    first["energy_rate_vnd_per_kwh"] = 2**63 - 1
    assert (await client_factory(station.id, first, actor)).status_code == 201
    assert (
        await client_factory(station.id, payload(today + timedelta(days=1)), actor)
    ).status_code == 201
    result = (await read()).json()
    assert result["has_versions"] is True
    assert result["current"]["effective_from"] == today.isoformat()
    assert result["current"]["bands"][0]["energy_rate_vnd_per_kwh"] == str(2**63 - 1)
    assert (
        result["upcoming"]["effective_from"] == (today + timedelta(days=1)).isoformat()
    )


@pytest.mark.parametrize(
    "roles,expected",
    [(set(), 401), ({"driver"}, 403), ({"admin"}, 403), ({"station_owner"}, 403)],
)
async def test_t62_context_rejects_anonymous_non_owner_and_cross_owner(
    api_db, roles, expected
):
    station, _ = await setup_station(api_db)
    if roles:
        app.dependency_overrides[get_current_actor] = lambda: CurrentActor(
            uuid4(), frozenset(roles)
        )
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            result = await client.get(
                f"/api/v1/owner/stations/{station.id}/tariffs/context"
            )
        assert result.status_code == expected
    finally:
        app.dependency_overrides.pop(get_current_actor, None)


async def test_create_versions_and_reject_duplicate(api_db, client_factory):
    station, actor = await setup_station(api_db)
    today = datetime.now(ZoneInfo(station.timezone)).date()
    first = await client_factory(station.id, payload(today), actor)
    assert first.status_code == 201, first.text
    data = first.json()
    assert data["station_id"] == str(station.id)
    assert data["effective_from"] == today.isoformat()
    assert len(data["bands"]) == 1
    assert (data["bands"][0]["start_min"], data["bands"][0]["end_min"]) == (0, 1440)
    assert data["bands"][0]["energy_rate_vnd_per_kwh"] == 2500
    assert (await client_factory(station.id, payload(today), actor)).status_code == 422
    tomorrow = today + timedelta(days=1)
    assert (
        await client_factory(station.id, payload(tomorrow), actor)
    ).status_code == 201
    assert (
        await client_factory(station.id, payload(tomorrow), actor)
    ).status_code == 409
    async with api_db() as session:
        assert await session.scalar(select(func.count()).select_from(Tariff)) == 2
        assert await session.scalar(select(func.count()).select_from(TariffBand)) == 2


async def test_other_owner_and_missing_station(api_db, client_factory):
    station, _ = await setup_station(api_db)
    actor = CurrentActor(uuid4(), frozenset({"station_owner"}))
    today = datetime.now(ZoneInfo(station.timezone)).date()
    assert (await client_factory(station.id, payload(today), actor)).status_code == 403
    assert (await client_factory(uuid4(), payload(today), actor)).status_code == 404
    async with api_db() as session:
        assert await session.scalar(select(func.count()).select_from(Tariff)) == 0


@pytest.mark.parametrize("zone", ["Pacific/Kiritimati", "America/Los_Angeles"])
async def test_local_day_and_failure_is_atomic(api_db, client_factory, zone):
    station, actor = await setup_station(api_db, zone)
    today = datetime.now(ZoneInfo(zone)).date()
    for day in (today - timedelta(days=1), today + timedelta(days=1)):
        response = await client_factory(station.id, payload(day), actor)
        assert response.status_code == 422
        assert response.json()["detail"][0]["loc"] == ["body", "effective_from"]
    async with api_db() as session:
        assert await session.scalar(select(func.count()).select_from(Tariff)) == 0
        assert await session.scalar(select(func.count()).select_from(TariffBand)) == 0
    assert (await client_factory(station.id, payload(today), actor)).status_code == 201


async def test_concurrent_first_creation(api_db):
    station, actor = await setup_station(api_db)
    today = datetime.now(ZoneInfo(station.timezone)).date()
    app.dependency_overrides[get_current_actor] = lambda: actor
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            responses = await asyncio.gather(
                *[
                    client.post(
                        f"/api/v1/owner/stations/{station.id}/tariffs",
                        json=payload(today),
                    )
                    for _ in range(2)
                ]
            )
        assert sorted(r.status_code for r in responses) == [201, 422]
        async with api_db() as session:
            assert await session.scalar(select(func.count()).select_from(Tariff)) == 1
            assert (
                await session.scalar(select(func.count()).select_from(TariffBand)) == 1
            )
    finally:
        app.dependency_overrides.pop(get_current_actor, None)


async def test_band_write_failure_rolls_back_tariff(api_db, monkeypatch):
    station, actor = await setup_station(api_db)
    today = datetime.now(ZoneInfo(station.timezone)).date()
    original_flush = AsyncSession.flush

    async def fail_band_flush(session, *args, **kwargs):
        if any(isinstance(row, TariffBand) for row in session.new):
            raise RuntimeError("Injected band write failure")
        return await original_flush(session, *args, **kwargs)

    monkeypatch.setattr(AsyncSession, "flush", fail_band_flush)
    app.dependency_overrides[get_current_actor] = lambda: actor
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://test",
        ) as client:
            response = await client.post(
                f"/api/v1/owner/stations/{station.id}/tariffs", json=payload(today)
            )
        assert response.status_code == 500
        async with api_db() as session:
            assert await session.scalar(select(func.count()).select_from(Tariff)) == 0
            assert (
                await session.scalar(select(func.count()).select_from(TariffBand)) == 0
            )
    finally:
        app.dependency_overrides.pop(get_current_actor, None)
