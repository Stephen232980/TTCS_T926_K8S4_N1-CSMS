import asyncio
from datetime import UTC, datetime, timedelta
from time import perf_counter
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.identity.authorization import CurrentActor
from src.modules.identity.models import User
from src.modules.ocpp import transport
from src.modules.ocpp.dispatcher import process_call
from src.modules.ocpp.frames import Frame, decode_frame
from src.modules.ocpp.monitor_router import MonitorQuery, monitoring_snapshot
from src.modules.ocpp.monitoring import expire_chargers, mark_seen
from src.modules.stations.models import ChargePoint, Connector, ConnectorError, Station
from src.platform.database.session import SessionFactory
from tests.test_ocpp_foundation import charger_fixture, connection


async def setup_charger(session):
    station, charger = await charger_fixture(session)
    charger.last_seen_at = datetime.now(UTC)
    charger.heartbeat_interval_seconds = 60
    connector = Connector(
        charge_point_id=charger.id, connector_number=1, status="Available"
    )
    session.add(connector)
    await session.flush()
    conn = connection(charger.id, station.id)
    conn.boot_accepted = True
    return station, charger, connector, conn


@pytest.mark.asyncio
async def test_server_clock_and_targeted_last_seen_update(db_session: AsyncSession):
    _, charger, _, conn = await setup_charger(db_session)
    await db_session.refresh(charger)
    before = charger.updated_at
    now = datetime.now(UTC)
    await mark_seen(db_session, charger.id, now)
    await db_session.refresh(charger)
    assert charger.last_seen_at == now and charger.updated_at == before
    reply = decode_frame(
        await process_call(
            conn, Frame(2, "heartbeat", {}, action="Heartbeat"), db_session
        )
    )
    assert reply.kind == 3
    assert (
        abs(
            (datetime.fromisoformat(reply.payload["currentTime"]) - now).total_seconds()
        )
        < 2
    )
    assert charger.status == "online"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "raw", ['[3,"reply",{}]', "malformed", '[2,"unknown","Other",{}]']
)
async def test_every_text_frame_records_contact(monkeypatch, raw):
    record = AsyncMock()
    monkeypatch.setattr(transport, "record_contact", record)
    monkeypatch.setattr(
        transport, "dispatch_call", AsyncMock(return_value='[3,"unknown",{}]')
    )
    conn = connection(uuid4(), uuid4())
    await transport.handle_message(conn, raw)
    if raw.startswith("[2,"):
        transport.dispatch_call.assert_awaited_once_with(
            conn, decode_frame(raw), record_seen=True
        )
    else:
        record.assert_awaited_once_with(conn)


@pytest.mark.asyncio
async def test_status_errors_duplicates_whole_charger_and_unknown(
    db_session: AsyncSession, caplog
):
    _, charger, connector, conn = await setup_charger(db_session)
    payload = {
        "connectorId": 1,
        "status": "Faulted",
        "errorCode": "GroundFailure",
        "vendorErrorCode": "E42",
        "timestamp": "2000-01-01T00:00:00Z",
    }
    frame = Frame(2, "fault", payload, action="StatusNotification")
    reply = await process_call(conn, frame, db_session)
    assert decode_frame(reply).payload == {}
    assert await process_call(conn, frame, db_session) == reply
    await db_session.refresh(connector)
    assert connector.status == "Faulted" and connector.raw_ocpp_status == "Faulted"
    errors = list(
        await db_session.scalars(
            select(ConnectorError).where(ConnectorError.connector_id == connector.id)
        )
    )
    assert len(errors) == 1 and errors[0].vendor_error_code == "E42"
    assert abs((errors[0].occurred_at - datetime.now(UTC)).total_seconds()) < 2
    await process_call(
        conn,
        Frame(
            2,
            "whole",
            {"connectorId": 0, "status": "Unavailable", "errorCode": "NoError"},
            action="StatusNotification",
        ),
        db_session,
    )
    await db_session.refresh(charger)
    assert charger.raw_ocpp_status == "Unavailable"
    await process_call(
        conn,
        Frame(
            2,
            "unknown",
            {"connectorId": 99, "status": "Charging", "errorCode": "NoError"},
            action="StatusNotification",
        ),
        db_session,
    )
    assert "ocpp_unknown_connector" in caplog.text
    assert (
        len(
            list(
                await db_session.scalars(
                    select(Connector).where(Connector.charge_point_id == charger.id)
                )
            )
        )
        == 1
    )
    actor = CurrentActor(uuid4(), frozenset({"operator"}))
    data = await monitoring_snapshot(db_session, actor, MonitorQuery())
    observed = next(c for c in data.items if c.id == charger.id)
    assert observed.connectors[0].last_error_code == "GroundFailure"
    assert observed.connectors[0].last_vendor_error_code == "E42"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {"connectorId": -1, "status": "Charging", "errorCode": "NoError"},
        {"connectorId": True, "status": "Charging", "errorCode": "NoError"},
        {"connectorId": 1, "status": "Wrong", "errorCode": "NoError"},
        {"connectorId": 1, "status": "Charging", "errorCode": "Wrong"},
        {
            "connectorId": 1,
            "status": "Charging",
            "errorCode": "NoError",
            "timestamp": "bad",
        },
        {
            "connectorId": 1,
            "status": "Charging",
            "errorCode": "NoError",
            "vendorErrorCode": None,
        },
    ],
)
async def test_monitoring_payload_validation(db_session: AsyncSession, payload):
    _, _, connector, conn = await setup_charger(db_session)
    reply = decode_frame(
        await process_call(
            conn, Frame(2, "bad", payload, action="StatusNotification"), db_session
        )
    )
    assert reply.kind == 4
    await db_session.refresh(connector)
    assert connector.status == "Available"


@pytest.mark.asyncio
async def test_offline_derived_without_job_then_recovery_waits_for_status(
    db_session: AsyncSession,
):
    station, charger, connector, conn = await setup_charger(db_session)
    now = datetime.now(UTC)
    charger.last_seen_at = now - timedelta(seconds=121)
    await db_session.flush()
    owner = CurrentActor(station.owner_id, frozenset({"station_owner"}))
    snapshot = await monitoring_snapshot(db_session, owner, MonitorQuery(), now)
    assert not snapshot.items[0].online
    assert snapshot.items[0].connectors[0].status == "unknown"
    # Recovery before the background job runs must also invalidate the old connector observation.
    await mark_seen(db_session, charger.id, now)
    await process_call(conn, Frame(2, "recover", {}, action="Heartbeat"), db_session)
    await db_session.refresh(connector)
    assert connector.status == "unknown"
    assert (
        (await monitoring_snapshot(db_session, owner, MonitorQuery(), now))
        .items[0]
        .online
    )
    await process_call(
        conn,
        Frame(
            2,
            "fresh",
            {"connectorId": 1, "status": "Charging", "errorCode": "NoError"},
            action="StatusNotification",
        ),
        db_session,
    )
    await db_session.refresh(connector)
    assert connector.status == "Charging"
    await expire_chargers(db_session, now + timedelta(seconds=121))
    await db_session.refresh(charger)
    await db_session.refresh(connector)
    assert charger.status == "offline" and connector.status == "unknown"


@pytest.mark.asyncio
async def test_twenty_chargers_one_snapshot_query_under_two_seconds(
    db_session: AsyncSession, monkeypatch
):
    station, charger, _, _ = await setup_charger(db_session)
    for number in range(19):
        cp = ChargePoint(
            station_id=station.id,
            code=f"perf-{uuid4()}",
            last_seen_at=datetime.now(UTC),
        )
        db_session.add(cp)
        await db_session.flush()
        db_session.add(
            Connector(charge_point_id=cp.id, connector_number=1, status="Available")
        )
    await db_session.flush()
    execute = AsyncMock(wraps=db_session.execute)
    monkeypatch.setattr(db_session, "execute", execute)
    start = perf_counter()
    snapshot = await monitoring_snapshot(
        db_session,
        CurrentActor(station.owner_id, frozenset({"station_owner"})),
        MonitorQuery(),
    )
    assert perf_counter() - start < 2
    assert len(snapshot.items) == 20 and all(
        len(c.connectors) == 1 for c in snapshot.items
    )
    assert execute.await_count == 1
    assert charger.id in {c.id for c in snapshot.items}


@pytest.mark.asyncio
async def test_fifty_simultaneous_contact_and_status_updates():
    ids = []
    async with SessionFactory() as session, session.begin():
        station, first = await charger_fixture(session)
        owner_id, station_id = station.owner_id, station.id
        ids.append(first.id)
        for _ in range(49):
            cp = ChargePoint(station_id=station.id, code=f"load-{uuid4()}")
            session.add(cp)
            await session.flush()
            ids.append(cp.id)
    try:

        async def touch(cp_id):
            async with SessionFactory() as session, session.begin():
                await mark_seen(session, cp_id)
                conn = connection(cp_id, station_id)
                conn.boot_accepted = True
                await process_call(
                    conn,
                    Frame(
                        2,
                        str(uuid4()),
                        {
                            "connectorId": 0,
                            "status": "Available",
                            "errorCode": "NoError",
                        },
                        action="StatusNotification",
                    ),
                    session,
                )

        await asyncio.gather(*(touch(cp_id) for cp_id in ids))
        async with SessionFactory() as session:
            seen = list(
                await session.scalars(
                    select(ChargePoint.last_seen_at).where(ChargePoint.id.in_(ids))
                )
            )
            assert len(seen) == 50 and all(seen)
            statuses = list(
                await session.scalars(
                    select(ChargePoint.raw_ocpp_status).where(ChargePoint.id.in_(ids))
                )
            )
            assert statuses == ["Available"] * 50
    finally:
        async with SessionFactory() as session, session.begin():
            await session.execute(delete(ChargePoint).where(ChargePoint.id.in_(ids)))
            await session.execute(delete(Station).where(Station.id == station_id))
            await session.execute(delete(User).where(User.id == owner_id))


@pytest.mark.asyncio
async def test_event_stream_refreshes_full_state_and_revokes_access(
    db_session: AsyncSession, monkeypatch
):
    from unittest.mock import MagicMock

    from src.modules.ocpp import monitor_router

    station, charger, connector, conn = await setup_charger(db_session)
    actor = CurrentActor(station.owner_id, frozenset({"station_owner"}))
    factory = MagicMock()
    factory.return_value.__aenter__ = AsyncMock(return_value=db_session)
    factory.return_value.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr(monitor_router, "SessionFactory", factory)
    authenticate = AsyncMock(return_value=actor)
    monkeypatch.setattr(
        monitor_router.IdentityRepository,
        "get_current_actor_by_session_hash",
        authenticate,
    )
    request = MagicMock()
    request.cookies = {"session": "test-only"}
    request.is_disconnected = AsyncMock(return_value=False)
    stream = monitor_router.monitoring_events(request, actor, MonitorQuery())
    first = await anext(stream)
    assert "Available" in first and "retry: 1000" in first
    await process_call(
        conn,
        Frame(
            2,
            "stream-update",
            {"connectorId": 1, "status": "Charging", "errorCode": "NoError"},
            action="StatusNotification",
        ),
        db_session,
    )
    started = perf_counter()
    second = await anext(stream)
    assert perf_counter() - started < 1 and "Charging" in second
    assert str(charger.id) in second and str(connector.id) in second
    await stream.aclose()
    # A new connection always gets a full snapshot, with the current state.
    stream = monitor_router.monitoring_events(request, actor, MonitorQuery())
    assert "Charging" in await anext(stream)
    authenticate.return_value = CurrentActor(actor.user_id, frozenset({"driver"}))
    assert "access-denied" in await anext(stream)
    with pytest.raises(StopAsyncIteration):
        await anext(stream)
