from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.entrypoints.http import app
from src.modules.identity.authorization import CurrentActor
from src.modules.identity.dependencies import get_current_actor
from src.modules.identity.models import User
from src.modules.stations.models import ChargePoint, Connector, Station
from src.modules.stations.repository import StationRepository
from src.platform.database.session import get_db_session


@asynccontextmanager
async def charge_point_api_client(
    db_session: AsyncSession,
    actor: CurrentActor,
) -> AsyncIterator[AsyncClient]:
    async def override_db_session() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_db_session] = override_db_session
    app.dependency_overrides[get_current_actor] = lambda: actor
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            yield client
    finally:
        app.dependency_overrides.clear()


async def create_charge_point(
    db_session: AsyncSession,
    *,
    code_locked_at: datetime | None = None,
) -> tuple[User, ChargePoint]:
    owner = User(
        email=f"charge-point-update-{uuid4()}@example.com",
        password_hash="hashed-password",
    )
    db_session.add(owner)
    await db_session.flush()

    station = Station(
        owner_id=owner.id,
        name="Tram thu sua ma tru",
        address="Dia chi thu sua ma tru",
        latitude=Decimal("10.700000"),
        longitude=Decimal("106.700000"),
    )
    db_session.add(station)
    await db_session.flush()

    charge_point = ChargePoint(
        station_id=station.id,
        code=f"CP-ORIGINAL-{uuid4()}",
        code_locked_at=code_locked_at,
        connectors=[Connector(connector_number=1)],
    )
    db_session.add(charge_point)
    await db_session.flush()
    return owner, charge_point


def owner_actor(owner_id: UUID) -> CurrentActor:
    return CurrentActor(
        user_id=owner_id,
        roles=frozenset({"station_owner"}),
    )


@pytest.mark.asyncio
async def test_owner_can_update_code_before_first_charging_session(
    db_session: AsyncSession,
) -> None:
    owner, charge_point = await create_charge_point(db_session)
    new_code = f"CP-UPDATED-{uuid4()}"

    async with charge_point_api_client(db_session, owner_actor(owner.id)) as client:
        response = await client.patch(
            f"/api/v1/charge-points/{charge_point.id}",
            json={"code": f"  {new_code}  "},
        )

    assert response.status_code == 200
    assert response.json()["code"] == new_code
    await db_session.refresh(charge_point)
    assert charge_point.code == new_code


@pytest.mark.asyncio
async def test_owner_cannot_update_code_after_charging_has_started(
    db_session: AsyncSession,
) -> None:
    locked_at = datetime.now(UTC)
    owner, charge_point = await create_charge_point(
        db_session,
        code_locked_at=locked_at,
    )
    original_code = charge_point.code

    async with charge_point_api_client(db_session, owner_actor(owner.id)) as client:
        response = await client.patch(
            f"/api/v1/charge-points/{charge_point.id}",
            json={"code": f"CP-BLOCKED-{uuid4()}"},
        )

    assert response.status_code == 409
    assert response.json() == {"detail": "charge_point_code_locked_after_charging"}
    await db_session.refresh(charge_point)
    assert charge_point.code == original_code


@pytest.mark.asyncio
async def test_update_code_rejects_code_used_by_another_charge_point(
    db_session: AsyncSession,
) -> None:
    owner, charge_point = await create_charge_point(db_session)
    _, existing_charge_point = await create_charge_point(db_session)

    async with charge_point_api_client(db_session, owner_actor(owner.id)) as client:
        response = await client.patch(
            f"/api/v1/charge-points/{charge_point.id}",
            json={"code": existing_charge_point.code.swapcase()},
        )

    assert response.status_code == 409
    assert response.json() == {"detail": "charge_point_code_already_exists"}


@pytest.mark.asyncio
async def test_owner_cannot_update_another_owners_charge_point(
    db_session: AsyncSession,
    caplog: pytest.LogCaptureFixture,
) -> None:
    owner_a, _ = await create_charge_point(db_session)
    _, charge_point_b = await create_charge_point(db_session)

    caplog.set_level("WARNING", logger="csms.security")
    async with charge_point_api_client(db_session, owner_actor(owner_a.id)) as client:
        response = await client.patch(
            f"/api/v1/charge-points/{charge_point_b.id}",
            json={"code": f"CP-DENIED-{uuid4()}"},
        )

    assert response.status_code == 403
    assert response.json() == {"detail": "permission_denied"}
    assert "cross_owner_charge_point_access_denied" in caplog.text
    assert str(owner_a.id) in caplog.text
    assert str(charge_point_b.id) in caplog.text


@pytest.mark.asyncio
async def test_database_rejects_locked_charge_point_code_update(
    db_session: AsyncSession,
) -> None:
    _, charge_point = await create_charge_point(
        db_session,
        code_locked_at=datetime.now(UTC),
    )

    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await db_session.execute(
                update(ChargePoint)
                .where(ChargePoint.id == charge_point.id)
                .values(code=f"CP-DIRECT-{uuid4()}")
            )


@pytest.mark.asyncio
async def test_charging_flow_can_lock_code_once_idempotently(
    db_session: AsyncSession,
) -> None:
    _, charge_point = await create_charge_point(db_session)
    first_started_at = datetime.now(UTC)

    repository = StationRepository(db_session)
    await repository.lock_charge_point_code_for_charging(
        charge_point.id,
        locked_at=first_started_at,
    )
    await repository.lock_charge_point_code_for_charging(
        charge_point.id,
        locked_at=datetime.now(UTC),
    )
    await db_session.flush()
    await db_session.refresh(charge_point)

    assert charge_point.code_locked_at == first_started_at
