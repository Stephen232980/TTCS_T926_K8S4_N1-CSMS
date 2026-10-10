import asyncio
import hashlib
import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import delete, text

from src.modules.charging.models import ChargingSession
from src.modules.charging.payloads import StartPayload
from src.modules.charging.service import start_transaction
from src.modules.identity.authorization import ActorScope, CurrentActor
from src.modules.identity.models import User
from src.modules.ocpp.frames import Frame
from src.modules.stations.exceptions import StationTimezoneLockedError
from src.modules.stations.models import ChargePoint, Connector, Station
from src.modules.stations.repository import StationRepository
from src.modules.stations.router import _station_create_request_hash
from src.modules.stations.schemas import StationCreateRequest, StationUpdateRequest
from src.platform.database.session import SessionFactory
from tests.test_ocpp_foundation import charger_fixture
from tests.test_station_authorization_integration import station_api_client

CREATE = {"name": "Timezone", "address": "Test", "latitude": "10", "longitude": "106"}


@pytest.mark.parametrize(
    "timezone", ["", "Not/AZone", "+07:00", "../Asia/Tokyo", "/etc/passwd"]
)
def test_reject_invalid_timezone_in_schema_and_model(timezone):
    with pytest.raises(ValidationError):
        StationCreateRequest(**CREATE, timezone=timezone)
    with pytest.raises(ValidationError):
        StationUpdateRequest(timezone=timezone)
    with pytest.raises(ValueError):
        Station(timezone=timezone)


def test_default_timezone_and_legacy_create_hash_are_compatible():
    request = StationCreateRequest(**CREATE)
    assert request.timezone == "Asia/Ho_Chi_Minh"
    old_payload = request.model_dump(mode="json", exclude={"timezone"})
    expected = hashlib.sha256(
        json.dumps(
            old_payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True
        ).encode()
    ).hexdigest()
    assert _station_create_request_hash(request) == expected
    assert (
        _station_create_request_hash(
            StationCreateRequest(**CREATE, timezone="Asia/Ho_Chi_Minh")
        )
        == expected
    )
    assert (
        _station_create_request_hash(
            StationCreateRequest(**CREATE, timezone="Asia/Tokyo")
        )
        != expected
    )
    with pytest.raises(ValidationError):
        StationUpdateRequest(timezone=None)


@pytest.mark.asyncio
async def test_create_read_update_timezone_http_and_idempotency(db_session):
    owner = User(email=f"tz-{uuid4()}@example.com", password_hash="unused")
    db_session.add(owner)
    await db_session.flush()
    actor = CurrentActor(user_id=owner.id, roles=frozenset({"station_owner"}))
    key = {"Idempotency-Key": str(uuid4())}
    async with station_api_client(db_session, actor) as client:
        created = await client.post("/api/v1/stations", json=CREATE, headers=key)
        assert created.status_code == 201
        assert created.json()["timezone"] == "Asia/Ho_Chi_Minh"
        station_id = created.json()["id"]
        updated = await client.patch(
            f"/api/v1/stations/{station_id}", json={"timezone": "Asia/Tokyo"}
        )
        assert updated.status_code == 200
        assert updated.json()["timezone"] == "Asia/Tokyo"
        read = await client.get(f"/api/v1/stations/{station_id}")
        assert read.json()["timezone"] == "Asia/Tokyo"
        conflict = await client.post(
            "/api/v1/stations", json={**CREATE, "timezone": "Asia/Tokyo"}, headers=key
        )
        assert conflict.status_code == 409
        custom = await client.post(
            "/api/v1/stations",
            json={**CREATE, "timezone": "Europe/Paris"},
            headers={"Idempotency-Key": str(uuid4())},
        )
        assert custom.status_code == 201
        assert custom.json()["timezone"] == "Europe/Paris"
        for payload in [{"timezone": "invalid"}, {"timezone": None}]:
            invalid = await client.patch(f"/api/v1/stations/{station_id}", json=payload)
            assert invalid.status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize("ended", [False, True])
async def test_any_session_locks_timezone_but_same_value_and_other_fields_allowed(
    db_session, ended
):
    station, charger = await charger_fixture(db_session)
    connector = Connector(charge_point_id=charger.id, connector_number=1)
    db_session.add(connector)
    await db_session.flush()
    db_session.add(
        ChargingSession(
            charge_point_id=charger.id,
            connector_id=connector.id,
            tag_tail="TEST",
            authorization_status="Invalid",
            started_at=datetime.now(UTC),
            ended_at=datetime.now(UTC) if ended else None,
            meter_start_wh=0,
            review_reasons=[],
        )
    )
    await db_session.flush()
    actor = CurrentActor(user_id=station.owner_id, roles=frozenset({"station_owner"}))
    async with station_api_client(db_session, actor) as client:
        locked = await client.patch(
            f"/api/v1/stations/{station.id}",
            json={"timezone": "Asia/Tokyo", "name": "Must not change"},
        )
        assert locked.status_code == 409
        assert locked.json() == {"detail": "station_timezone_locked"}
        assert station.name == "OCPP fixture"
        same = await client.patch(
            f"/api/v1/stations/{station.id}",
            json={"timezone": "Asia/Ho_Chi_Minh", "name": "Still editable"},
        )
        assert same.status_code == 200
        assert same.json()["name"] == "Still editable"
        stranger = CurrentActor(user_id=uuid4(), roles=frozenset({"station_owner"}))
    async with station_api_client(db_session, stranger) as client:
        denied = await client.patch(
            f"/api/v1/stations/{station.id}", json={"timezone": "UTC"}
        )
        assert denied.status_code == 403


async def wait_for_database_lock(pid):
    # Verify actual PostgreSQL blocking, not timing of coroutine scheduling.
    async with SessionFactory() as observer:
        async with asyncio.timeout(5):
            while not await observer.scalar(
                text("SELECT cardinality(pg_blocking_pids(:pid)) > 0"), {"pid": pid}
            ):
                await asyncio.sleep(0.01)


@pytest.mark.asyncio
@pytest.mark.parametrize("session_first", [True, False])
async def test_first_session_and_timezone_change_serialize_across_connections(
    session_first,
):
    async with SessionFactory() as setup, setup.begin():
        station, charger = await charger_fixture(setup)
        setup.add(Connector(charge_point_id=charger.id, connector_number=1))
        await setup.flush()
        station_id, charger_id, owner_id = station.id, charger.id, station.owner_id
    scope = ActorScope(actor_id=owner_id, owner_id=owner_id)

    async def change_timezone(session):
        return await StationRepository(session).update_station(
            station_id,
            scope,
            name=None,
            address=None,
            latitude=None,
            longitude=None,
            timezone="Asia/Tokyo",
        )

    async def start(session):
        cp = await session.get(ChargePoint, charger_id)
        return await start_transaction(
            session,
            cp,
            Frame(2, str(uuid4()), {}, action="StartTransaction"),
            StartPayload(
                connectorId=1,
                idTag="UNKNOWN",
                meterStart=0,
                timestamp=datetime.now(UTC),
            ),
        )

    pending = None
    try:
        async with SessionFactory() as first, SessionFactory() as second:
            second_pid = await second.scalar(text("SELECT pg_backend_pid()"))
            if session_first:
                await start(first)
                pending = asyncio.create_task(change_timezone(second))
            else:
                await change_timezone(first)
                pending = asyncio.create_task(start(second))
            try:
                await wait_for_database_lock(second_pid)
                await first.commit()
                if session_first:
                    with pytest.raises(StationTimezoneLockedError):
                        await pending
                    await second.rollback()
                else:
                    await pending
                    await second.commit()
            finally:
                if not pending.done():
                    pending.cancel()
                await asyncio.gather(pending, return_exceptions=True)
        async with SessionFactory() as verify:
            saved = await verify.get(Station, station_id)
            assert saved.timezone == (
                "Asia/Ho_Chi_Minh" if session_first else "Asia/Tokyo"
            )
            with pytest.raises(StationTimezoneLockedError):
                await StationRepository(verify).update_station(
                    station_id,
                    scope,
                    name=None,
                    address=None,
                    latitude=None,
                    longitude=None,
                    timezone="UTC",
                )
    finally:
        async with SessionFactory() as cleanup, cleanup.begin():
            await cleanup.execute(
                delete(ChargingSession).where(
                    ChargingSession.charge_point_id == charger_id
                )
            )
            await cleanup.execute(
                delete(Connector).where(Connector.charge_point_id == charger_id)
            )
            await cleanup.execute(
                delete(ChargePoint).where(ChargePoint.id == charger_id)
            )
            await cleanup.execute(delete(Station).where(Station.id == station_id))
            await cleanup.execute(delete(User).where(User.id == owner_id))
