from datetime import UTC, datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from src.entrypoints.http import app
from src.modules.identity.authorization import CurrentActor
from src.modules.identity.dependencies import get_current_actor
from src.modules.pricing.models import Tariff, TariffBand
from tests import test_flat_tariff_api as flat
from tests.test_multi_band_tariff_api import band, payload

committed_tariff_db = flat.committed_tariff_db
api_db = flat.api_db
client_factory = flat.client_factory


async def request(station_id, actor, method="GET", suffix="", body=None):
    if actor is not None:
        app.dependency_overrides[get_current_actor] = lambda: actor
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.request(
                method,
                f"/api/v1/owner/stations/{station_id}/tariffs{suffix}",
                json=body,
            )
    finally:
        app.dependency_overrides.pop(get_current_actor, None)


async def versions(api_db, client_factory, zone="Asia/Ho_Chi_Minh"):
    station, actor = await flat.setup_station(api_db, zone)
    today = datetime.now(ZoneInfo(zone)).date()
    first = await client_factory(station.id, payload(today), actor)
    future = await client_factory(station.id, payload(today + timedelta(days=1)), actor)
    assert first.status_code == future.status_code == 201
    return station, actor, today, first.json()["id"], future.json()["id"]


@pytest.mark.parametrize(
    "roles,status",
    [(None, 401), ({"driver"}, 403), ({"admin"}, 403), ({"operator"}, 403)],
)
@pytest.mark.parametrize("method", ["GET", "PATCH"])
async def test_role_denied(roles, status, method):
    actor = CurrentActor(uuid4(), frozenset(roles)) if roles else None
    result = await request(
        uuid4(),
        actor,
        method,
        f"/{uuid4()}" if method == "PATCH" else "",
        payload(datetime.now(UTC).date()) if method == "PATCH" else None,
    )
    assert result.status_code == status


async def test_history_timezone_status_pagination_exact_money(api_db, client_factory):
    station, actor, today, first, future = await versions(
        api_db, client_factory, "Pacific/Kiritimati"
    )
    async with api_db() as db:
        row = await db.scalar(
            select(TariffBand).where(TariffBand.tariff_id == future).limit(1)
        )
        row.energy_rate_vnd_per_kwh = 2**63 - 1
        await db.commit()
    result = await request(station.id, actor)
    assert result.headers["cache-control"] == "no-store"
    history = result.json()
    assert history["today"] == today.isoformat()
    assert history["timezone"] == "Pacific/Kiritimati"
    assert history["total"] == 2
    assert [(v["id"], v["status"], v["editable"]) for v in history["items"]] == [
        (future, "upcoming", True),
        (first, "current", False),
    ]
    assert history["items"][0]["bands"][0]["energy_rate_vnd_per_kwh"] == str(2**63 - 1)
    page2 = (await request(station.id, actor, suffix="?page=2&page_size=1")).json()
    assert page2["items"][0]["status"] == "current"
    assert page2["total"] == 2
    assert (await request(station.id, actor, suffix="?page=0")).status_code == 422
    assert (
        await request(station.id, actor, suffix="?page_size=101")
    ).status_code == 422


async def test_edit_future_atomic_and_effective_version_unchanged(
    api_db, client_factory
):
    station, actor, today, first, future = await versions(api_db, client_factory)
    before = (await request(station.id, actor)).json()["items"][1]
    body = payload(
        today + timedelta(days=2),
        [band(1320, 120, 2000, "Đêm"), band(120, 1320, 2**63 - 1, "Ngày")],
    )
    result = await request(station.id, actor, "PATCH", f"/{future}", body)
    assert result.status_code == 200, result.text
    assert result.json()["id"] == future
    assert result.json()["status"] == "upcoming"
    assert [(b["start_min"], b["end_min"]) for b in result.json()["bands"]] == [
        (0, 120),
        (120, 1320),
        (1320, 1440),
    ]
    assert result.json()["bands"][1]["energy_rate_vnd_per_kwh"] == str(2**63 - 1)
    assert (await request(station.id, actor)).json()["items"][1] == before
    denied = await request(station.id, actor, "PATCH", f"/{first}", body)
    assert denied.status_code == 409
    assert denied.json()["detail"] == "tariff_immutable"
    assert (await request(station.id, actor)).json()["items"][1] == before
    assert (await request(station.id, actor, "DELETE", f"/{future}")).status_code == 405


async def test_used_future_and_invalid_edit_preserve_data(api_db, client_factory):
    station, actor, today, _first, future = await versions(api_db, client_factory)
    before = (await request(station.id, actor)).json()["items"]
    invalid = payload(today + timedelta(days=2), [band(0, 600), band(660, 1440)])
    assert (
        await request(station.id, actor, "PATCH", f"/{future}", invalid)
    ).status_code == 422
    assert (await request(station.id, actor)).json()["items"] == before
    assert (
        await request(station.id, actor, "PATCH", f"/{future}", payload(today))
    ).status_code == 422
    assert (await request(station.id, actor)).json()["items"] == before
    async with api_db() as db:
        row = await db.get(Tariff, future)
        row.used_at = datetime.now(UTC)
        await db.commit()
    used = (await request(station.id, actor)).json()["items"][0]
    assert used["editable"] is False
    result = await request(
        station.id, actor, "PATCH", f"/{future}", payload(today + timedelta(days=2))
    )
    assert result.status_code == 409
    assert result.json()["detail"] == "tariff_immutable"
    assert (await request(station.id, actor)).json()["items"][0] == used


async def test_ownership_missing_and_duplicate_date(api_db, client_factory):
    station, actor, today, _first, future = await versions(api_db, client_factory)
    stranger = CurrentActor(uuid4(), frozenset({"station_owner"}))
    for method, suffix, body in [
        ("GET", "", None),
        ("PATCH", f"/{future}", payload(today + timedelta(days=2))),
    ]:
        assert (
            await request(station.id, stranger, method, suffix, body)
        ).status_code == 403
        assert (await request(uuid4(), actor, method, suffix, body)).status_code == 404
    assert (
        await request(
            station.id,
            actor,
            "PATCH",
            f"/{uuid4()}",
            payload(today + timedelta(days=2)),
        )
    ).status_code == 404
    third = await client_factory(station.id, payload(today + timedelta(days=2)), actor)
    assert third.status_code == 201
    before = (await request(station.id, actor)).json()
    result = await request(
        station.id, actor, "PATCH", f"/{future}", payload(today + timedelta(days=2))
    )
    assert result.status_code == 409
    assert result.json()["detail"] == "tariff_duplicate_date"
    assert (await request(station.id, actor)).json() == before
