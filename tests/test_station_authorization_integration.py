import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.entrypoints.http import app
from src.modules.identity.authorization import CurrentActor
from src.modules.identity.dependencies import get_current_actor
from src.modules.identity.models import User
from src.modules.stations.models import Station
from src.platform.database.session import get_db_session


@asynccontextmanager
async def station_api_client(
    db_session: AsyncSession,
    actor: CurrentActor,
) -> AsyncIterator[AsyncClient]:
    async def override_db_session() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_db_session] = override_db_session
    app.dependency_overrides[get_current_actor] = lambda: actor

    transport = ASGITransport(app=app)

    try:
        async with AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            yield client
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_owner_can_get_owned_station_through_http(
    db_session: AsyncSession,
) -> None:
    owner = User(
        email="station-http-owner@example.com",
        password_hash="hashed-password",
    )
    db_session.add(owner)
    await db_session.flush()

    station = Station(
        owner_id=owner.id,
        name="Trạm HTTP hợp lệ",
        address="Địa chỉ hợp lệ",
        latitude=Decimal("10.700000"),
        longitude=Decimal("106.700000"),
    )
    db_session.add(station)
    await db_session.flush()

    actor = CurrentActor(
        user_id=owner.id,
        roles=frozenset({"station_owner"}),
    )

    async with station_api_client(db_session, actor) as client:
        response = await client.get(f"/api/v1/stations/{station.id}")

    assert response.status_code == 200
    assert response.json()["id"] == str(station.id)
    assert response.json()["owner_id"] == str(owner.id)
    assert response.json()["name"] == "Trạm HTTP hợp lệ"


@pytest.mark.asyncio
async def test_cross_owner_station_request_returns_403_and_logs(
    db_session: AsyncSession,
    caplog: pytest.LogCaptureFixture,
) -> None:
    owner_a = User(
        email="station-http-cross-owner-a@example.com",
        password_hash="hashed-password",
    )
    owner_b = User(
        email="station-http-cross-owner-b@example.com",
        password_hash="hashed-password",
    )
    db_session.add_all([owner_a, owner_b])
    await db_session.flush()

    station_b = Station(
        owner_id=owner_b.id,
        name="Trạm HTTP của B",
        address="Địa chỉ B",
        latitude=Decimal("10.800000"),
        longitude=Decimal("106.800000"),
    )
    db_session.add(station_b)
    await db_session.flush()

    actor = CurrentActor(
        user_id=owner_a.id,
        roles=frozenset({"station_owner"}),
    )
    caplog.set_level(logging.WARNING, logger="csms.security")

    async with station_api_client(db_session, actor) as client:
        response = await client.get(f"/api/v1/stations/{station_b.id}")

    assert response.status_code == 403
    assert response.json() == {"detail": "permission_denied"}
    assert "cross_owner_station_access_denied" in caplog.text
    assert str(owner_a.id) in caplog.text
    assert str(station_b.id) in caplog.text
    assert owner_a.email not in caplog.text
    assert owner_b.email not in caplog.text


@pytest.mark.asyncio
async def test_missing_station_request_returns_404(
    db_session: AsyncSession,
) -> None:
    actor = CurrentActor(
        user_id=uuid4(),
        roles=frozenset({"station_owner"}),
    )

    async with station_api_client(db_session, actor) as client:
        response = await client.get(f"/api/v1/stations/{uuid4()}")

    assert response.status_code == 404
    assert response.json() == {"detail": "resource_not_found"}


@pytest.mark.asyncio
async def test_owner_lists_only_owned_stations_through_http(
    db_session: AsyncSession,
) -> None:
    owner_a = User(
        email="station-list-http-owner-a@example.com",
        password_hash="hashed-password",
    )
    owner_b = User(
        email="station-list-http-owner-b@example.com",
        password_hash="hashed-password",
    )
    db_session.add_all([owner_a, owner_b])
    await db_session.flush()

    station_a = Station(
        owner_id=owner_a.id,
        name="Trạm HTTP của A",
        address="Địa chỉ A",
        latitude=Decimal("10.700000"),
        longitude=Decimal("106.700000"),
    )
    station_b = Station(
        owner_id=owner_b.id,
        name="Trạm HTTP của B",
        address="Địa chỉ B",
        latitude=Decimal("10.800000"),
        longitude=Decimal("106.800000"),
    )
    db_session.add_all([station_a, station_b])
    await db_session.flush()

    actor = CurrentActor(
        user_id=owner_a.id,
        roles=frozenset({"station_owner"}),
    )

    async with station_api_client(db_session, actor) as client:
        response = await client.get(
            "/api/v1/stations",
            params={
                "page": 1,
                "page_size": 20,
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["page"] == 1
    assert payload["page_size"] == 20
    assert payload["total"] == 1
    assert payload["total_pages"] == 1
    assert [item["id"] for item in payload["items"]] == [str(station_a.id)]


@pytest.mark.asyncio
async def test_admin_lists_stations_in_global_scope_through_http(
    db_session: AsyncSession,
) -> None:
    owner_a = User(
        email="station-list-http-global-a@example.com",
        password_hash="hashed-password",
    )
    owner_b = User(
        email="station-list-http-global-b@example.com",
        password_hash="hashed-password",
    )
    db_session.add_all([owner_a, owner_b])
    await db_session.flush()

    stations = [
        Station(
            owner_id=owner_a.id,
            name="Trạm global A",
            address="Địa chỉ A",
            latitude=Decimal("10.700000"),
            longitude=Decimal("106.700000"),
        ),
        Station(
            owner_id=owner_b.id,
            name="Trạm global B",
            address="Địa chỉ B",
            latitude=Decimal("10.800000"),
            longitude=Decimal("106.800000"),
        ),
    ]
    db_session.add_all(stations)
    await db_session.flush()

    actor = CurrentActor(
        user_id=owner_a.id,
        roles=frozenset({"admin"}),
    )

    async with station_api_client(db_session, actor) as client:
        response = await client.get(
            "/api/v1/stations",
            params={
                "page": 1,
                "page_size": 20,
            },
        )

    assert response.status_code == 200
    returned_ids = {item["id"] for item in response.json()["items"]}
    assert returned_ids == {str(station.id) for station in stations}


@pytest.mark.asyncio
async def test_station_list_rejects_driver_role(
    db_session: AsyncSession,
) -> None:
    actor = CurrentActor(
        user_id=uuid4(),
        roles=frozenset({"driver"}),
    )

    async with station_api_client(db_session, actor) as client:
        response = await client.get("/api/v1/stations")

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_owner_creates_station_through_http(
    db_session: AsyncSession,
) -> None:
    owner = User(
        email="station-create-http-owner@example.com",
        password_hash="hashed-password",
    )
    db_session.add(owner)
    await db_session.flush()

    actor = CurrentActor(
        user_id=owner.id,
        roles=frozenset({"station_owner"}),
    )

    async with station_api_client(db_session, actor) as client:
        response = await client.post(
            "/api/v1/stations",
            headers={"Idempotency-Key": str(uuid4())},
            json={
                "name": "  Trạm Quận 1  ",
                "address": "  123 Nguyễn Huệ, Quận 1  ",
                "latitude": 10.7731,
                "longitude": 106.7032,
            },
        )

    assert response.status_code == 201
    payload = response.json()
    assert payload["owner_id"] == str(owner.id)
    assert payload["name"] == "Trạm Quận 1"
    assert payload["address"] == "123 Nguyễn Huệ, Quận 1"
    assert payload["latitude"] == 10.7731
    assert payload["longitude"] == 106.7032
    assert payload["status"] == "inactive"


@pytest.mark.asyncio
async def test_create_station_rejects_invalid_coordinates(
    db_session: AsyncSession,
) -> None:
    actor = CurrentActor(
        user_id=uuid4(),
        roles=frozenset({"station_owner"}),
    )

    async with station_api_client(db_session, actor) as client:
        response = await client.post(
            "/api/v1/stations",
            headers={"Idempotency-Key": str(uuid4())},
            json={
                "name": "Trạm sai tọa độ",
                "address": "Quận 1",
                "latitude": 90.01,
                "longitude": -180.01,
            },
        )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_driver_cannot_create_station(
    db_session: AsyncSession,
) -> None:
    actor = CurrentActor(
        user_id=uuid4(),
        roles=frozenset({"driver"}),
    )

    async with station_api_client(db_session, actor) as client:
        response = await client.post(
            "/api/v1/stations",
            headers={"Idempotency-Key": str(uuid4())},
            json={
                "name": "Trạm không được phép",
                "address": "Quận 1",
                "latitude": 10.7731,
                "longitude": 106.7032,
            },
        )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_create_station_requires_idempotency_key(
    db_session: AsyncSession,
) -> None:
    actor = CurrentActor(
        user_id=uuid4(),
        roles=frozenset({"station_owner"}),
    )

    async with station_api_client(db_session, actor) as client:
        response = await client.post(
            "/api/v1/stations",
            json={
                "name": "Trạm thiếu khóa",
                "address": "Quận 1",
                "latitude": 10.7731,
                "longitude": 106.7032,
            },
        )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_station_replays_same_idempotency_request(
    db_session: AsyncSession,
) -> None:
    owner = User(
        email="station-create-replay-owner@example.com",
        password_hash="hashed-password",
    )
    db_session.add(owner)
    await db_session.flush()

    actor = CurrentActor(
        user_id=owner.id,
        roles=frozenset({"station_owner"}),
    )
    headers = {"Idempotency-Key": str(uuid4())}
    payload = {
        "name": "Trạm idempotent",
        "address": "Quận 1",
        "latitude": 10.7731,
        "longitude": 106.7032,
    }

    async with station_api_client(db_session, actor) as client:
        first_response = await client.post(
            "/api/v1/stations",
            headers=headers,
            json=payload,
        )
        replay_response = await client.post(
            "/api/v1/stations",
            headers=headers,
            json=payload,
        )

    assert first_response.status_code == 201
    assert replay_response.status_code == 201
    assert replay_response.json()["id"] == first_response.json()["id"]


@pytest.mark.asyncio
async def test_create_station_rejects_reused_key_with_changed_payload(
    db_session: AsyncSession,
) -> None:
    owner = User(
        email="station-create-conflict-owner@example.com",
        password_hash="hashed-password",
    )
    db_session.add(owner)
    await db_session.flush()

    actor = CurrentActor(
        user_id=owner.id,
        roles=frozenset({"station_owner"}),
    )
    headers = {"Idempotency-Key": str(uuid4())}

    async with station_api_client(db_session, actor) as client:
        first_response = await client.post(
            "/api/v1/stations",
            headers=headers,
            json={
                "name": "Trạm ban đầu",
                "address": "Quận 1",
                "latitude": 10.7731,
                "longitude": 106.7032,
            },
        )
        conflict_response = await client.post(
            "/api/v1/stations",
            headers=headers,
            json={
                "name": "Trạm đã thay đổi",
                "address": "Quận 3",
                "latitude": 10.78,
                "longitude": 106.69,
            },
        )

    assert first_response.status_code == 201
    assert conflict_response.status_code == 409
    assert conflict_response.json() == {"detail": "idempotency_conflict"}


@pytest.mark.asyncio
async def test_owner_updates_station_and_sees_change_in_list(
    db_session: AsyncSession,
) -> None:
    owner = User(
        email="station-update-http-owner@example.com",
        password_hash="hashed-password",
    )
    db_session.add(owner)
    await db_session.flush()
    station = Station(
        owner_id=owner.id,
        name="Trạm ban đầu",
        address="Địa chỉ ban đầu",
        latitude=Decimal("10.700000"),
        longitude=Decimal("106.700000"),
    )
    db_session.add(station)
    await db_session.flush()
    actor = CurrentActor(
        user_id=owner.id,
        roles=frozenset({"station_owner"}),
    )

    async with station_api_client(db_session, actor) as client:
        update_response = await client.patch(
            f"/api/v1/stations/{station.id}",
            json={
                "name": "Trạm đã sửa",
                "address": "Địa chỉ đã sửa",
            },
        )
        list_response = await client.get("/api/v1/stations")

    assert update_response.status_code == 200
    assert update_response.json()["name"] == "Trạm đã sửa"
    assert update_response.json()["address"] == "Địa chỉ đã sửa"
    assert list_response.status_code == 200
    assert list_response.json()["items"][0]["name"] == "Trạm đã sửa"
    assert list_response.json()["items"][0]["address"] == "Địa chỉ đã sửa"


@pytest.mark.asyncio
async def test_update_station_rejects_invalid_payloads(
    db_session: AsyncSession,
) -> None:
    actor = CurrentActor(
        user_id=uuid4(),
        roles=frozenset({"station_owner"}),
    )

    async with station_api_client(db_session, actor) as client:
        empty_response = await client.patch(
            f"/api/v1/stations/{uuid4()}",
            json={},
        )
        null_response = await client.patch(
            f"/api/v1/stations/{uuid4()}",
            json={"name": None},
        )
        coordinates_response = await client.patch(
            f"/api/v1/stations/{uuid4()}",
            json={"latitude": 90.01, "longitude": -180.01},
        )

    assert empty_response.status_code == 422
    assert null_response.status_code == 422
    assert coordinates_response.status_code == 422


@pytest.mark.asyncio
async def test_update_missing_station_returns_404(
    db_session: AsyncSession,
) -> None:
    actor = CurrentActor(
        user_id=uuid4(),
        roles=frozenset({"station_owner"}),
    )

    async with station_api_client(db_session, actor) as client:
        response = await client.patch(
            f"/api/v1/stations/{uuid4()}",
            json={"name": "Trạm không tồn tại"},
        )

    assert response.status_code == 404
    assert response.json() == {"detail": "resource_not_found"}


@pytest.mark.asyncio
async def test_cross_owner_station_update_returns_403_and_logs(
    db_session: AsyncSession,
    caplog: pytest.LogCaptureFixture,
) -> None:
    owner_a = User(
        email="station-update-http-owner-a@example.com",
        password_hash="hashed-password",
    )
    owner_b = User(
        email="station-update-http-owner-b@example.com",
        password_hash="hashed-password",
    )
    db_session.add_all([owner_a, owner_b])
    await db_session.flush()
    station_b = Station(
        owner_id=owner_b.id,
        name="Trạm của B",
        address="Địa chỉ B",
        latitude=Decimal("10.800000"),
        longitude=Decimal("106.800000"),
    )
    db_session.add(station_b)
    await db_session.flush()
    actor = CurrentActor(
        user_id=owner_a.id,
        roles=frozenset({"station_owner"}),
    )
    caplog.set_level(logging.WARNING, logger="csms.security")

    async with station_api_client(db_session, actor) as client:
        response = await client.patch(
            f"/api/v1/stations/{station_b.id}",
            json={"name": "Không được phép"},
        )

    assert response.status_code == 403
    assert response.json() == {"detail": "permission_denied"}
    assert "cross_owner_station_access_denied" in caplog.text
    assert str(owner_a.id) in caplog.text
    assert str(station_b.id) in caplog.text


@pytest.mark.asyncio
async def test_driver_cannot_update_station(
    db_session: AsyncSession,
) -> None:
    actor = CurrentActor(
        user_id=uuid4(),
        roles=frozenset({"driver"}),
    )

    async with station_api_client(db_session, actor) as client:
        response = await client.patch(
            f"/api/v1/stations/{uuid4()}",
            json={"name": "Không được phép"},
        )

    assert response.status_code == 403
