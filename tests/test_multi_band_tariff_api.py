import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from src.entrypoints.http import app
from src.modules.identity.authorization import CurrentActor
from src.modules.identity.dependencies import get_current_actor
from src.modules.pricing.models import Tariff, TariffBand
from tests import test_flat_tariff_api as flat

committed_tariff_db = flat.committed_tariff_db
api_db = flat.api_db
client_factory = flat.client_factory
setup_station = flat.setup_station


def band(start, end, price=2500, label=""):
    return {
        "start_min": start,
        "end_min": end,
        "energy_rate_vnd_per_kwh": price,
        "label": label,
    }


def payload(day, bands=None):
    return {
        "effective_from": day.isoformat(),
        "idle_rate_vnd_per_minute": 1000,
        "grace_minutes": 5,
        "bands": bands
        if bands is not None
        else [band(0, 360, 2000), band(360, 1320, 4000), band(1320, 1440, 2000)],
    }


@pytest.mark.parametrize(
    "roles,status",
    [(None, 401), ({"driver"}, 403), ({"admin"}, 403), ({"operator"}, 403)],
)
async def test_access(client_factory, roles, status):
    actor = CurrentActor(uuid4(), frozenset(roles)) if roles else None
    response = await client_factory(uuid4(), payload(datetime.now(UTC).date()), actor)
    assert response.status_code == status


@pytest.mark.parametrize(
    "field,value",
    [
        ("start_min", -1),
        ("start_min", 1440),
        ("start_min", True),
        ("start_min", 1.5),
        ("end_min", 1441),
        ("end_min", "360"),
        ("energy_rate_vnd_per_kwh", -1),
        ("energy_rate_vnd_per_kwh", 1.5),
        ("energy_rate_vnd_per_kwh", True),
        ("energy_rate_vnd_per_kwh", 2**63),
        ("label", "x" * 101),
        ("tariff_id", str(uuid4())),
    ],
)
async def test_nested_validation(client_factory, field, value):
    body = payload(datetime.now(UTC).date())
    body["bands"][0][field] = value
    response = await client_factory(
        uuid4(), body, CurrentActor(uuid4(), frozenset({"station_owner"}))
    )
    assert response.status_code == 422
    assert any(
        i["loc"] == ["body", "bands", 0, field] for i in response.json()["detail"]
    )


@pytest.mark.parametrize(
    "extra",
    [
        {"energy_rate_vnd_per_kwh": 2500},
        {"energy_rate_vnd_per_kwh": None},
        {"label": "Ignored label"},
        {"bands": []},
        {"bands": None},
    ],
)
async def test_ambiguous_or_empty_body(client_factory, extra):
    body = payload(datetime.now(UTC).date()) | extra
    response = await client_factory(
        uuid4(), body, CurrentActor(uuid4(), frozenset({"station_owner"}))
    )
    assert response.status_code == 422


@pytest.mark.parametrize(
    "bands,expected",
    [
        (
            [band(0, 360), band(360, 1320), band(1320, 1440)],
            [(0, 360), (360, 1320), (1320, 1440)],
        ),
        (
            [band(1320, 120, 2000, "Đêm"), band(120, 1320, 4000)],
            [(0, 120), (120, 1320), (1320, 1440)],
        ),
        ([band(1320, 0, 2000), band(0, 1320, 0)], [(0, 1320), (1320, 1440)]),
    ],
)
async def test_create_and_normalize(api_db, client_factory, bands, expected):
    station, actor = await setup_station(api_db)
    today = datetime.now(ZoneInfo(station.timezone)).date()
    response = await client_factory(station.id, payload(today, bands), actor)
    assert response.status_code == 201, response.text
    rows = response.json()["bands"]
    assert [(b["start_min"], b["end_min"]) for b in rows] == expected
    async with api_db() as session:
        saved = (
            await session.scalars(select(TariffBand).order_by(TariffBand.start_min))
        ).all()
        assert [
            (b.start_min, b.end_min, b.energy_rate_vnd_per_kwh, b.label) for b in saved
        ] == [
            (b["start_min"], b["end_min"], b["energy_rate_vnd_per_kwh"], b["label"])
            for b in rows
        ]


async def test_all_coverage_errors_and_no_writes(api_db, client_factory):
    station, actor = await setup_station(api_db)
    today = datetime.now(ZoneInfo(station.timezone)).date()
    for bands, expected in [
        ([band(0, 360), band(420, 1440)], [("gap", 360, 420)]),
        ([band(0, 600), band(540, 1440)], [("overlap", 540, 600)]),
        (
            [band(60, 600), band(540, 1380)],
            [("gap", 0, 60), ("overlap", 540, 600), ("gap", 1380, 1440)],
        ),
        ([band(0, 1440), band(600, 660)], [("overlap", 600, 660)]),
    ]:
        response = await client_factory(station.id, payload(today, bands), actor)
        assert response.status_code == 422
        issues = response.json()["detail"]
        assert [(i["type"], i["start_min"], i["end_min"]) for i in issues] == expected
        assert all(i["loc"] == ["body", "bands"] for i in issues)
        for issue in issues:
            if issue["type"] == "overlap":
                assert issue["input_indices"] == [0, 1]
        if expected == [("gap", 360, 420)]:
            assert "06:00–07:00" in issues[0]["msg"]
    response = await client_factory(station.id, payload(today, [band(0, 0)]), actor)
    assert response.status_code == 422
    assert response.json()["detail"][0]["input_indices"] == [0]
    async with api_db() as session:
        assert await session.scalar(select(func.count()).select_from(Tariff)) == 0
        assert await session.scalar(select(func.count()).select_from(TariffBand)) == 0


async def test_owner_dates_and_flat_compatibility(api_db, client_factory):
    station, actor = await setup_station(api_db, "Pacific/Kiritimati")
    today = datetime.now(ZoneInfo(station.timezone)).date()
    outsider = CurrentActor(uuid4(), frozenset({"station_owner"}))
    assert (
        await client_factory(station.id, payload(today), outsider)
    ).status_code == 403
    assert (await client_factory(uuid4(), payload(today), actor)).status_code == 404
    assert (
        await client_factory(station.id, payload(today + timedelta(days=1)), actor)
    ).status_code == 422
    assert (
        await client_factory(station.id, flat.payload(today), actor)
    ).status_code == 201
    tomorrow = today + timedelta(days=1)
    assert (await client_factory(station.id, payload(today), actor)).status_code == 422
    assert (
        await client_factory(station.id, payload(tomorrow), actor)
    ).status_code == 201
    assert (
        await client_factory(station.id, payload(tomorrow), actor)
    ).status_code == 409


async def test_flat_and_multi_first_requests_share_lock(api_db):
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
                        f"/api/v1/owner/stations/{station.id}/tariffs", json=body
                    )
                    for body in [flat.payload(today), payload(today)]
                ]
            )
        assert sorted(r.status_code for r in responses) == [201, 422]
        async with api_db() as session:
            assert await session.scalar(select(func.count()).select_from(Tariff)) == 1
            count = await session.scalar(select(func.count()).select_from(TariffBand))
            assert count in (1, 3)
    finally:
        app.dependency_overrides.pop(get_current_actor, None)
