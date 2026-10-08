from datetime import datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select

from src.modules.identity.authorization import CurrentActor, build_actor_scope
from src.modules.ocpp import monitor_router, monitoring
from src.modules.ocpp.monitor_router import MonitorQuery, monitoring_snapshot
from tests.test_ocpp_monitoring import setup_charger


@pytest.mark.asyncio
@pytest.mark.parametrize("skew_days", [-7, 7])
async def test_liveness_uses_database_clock_despite_application_skew(
    db_session, monkeypatch, skew_days
):
    station, charger, connector, _ = await setup_charger(db_session)
    db_now = await monitoring.database_time(db_session)
    charger.status = "online"
    charger.last_seen_at = db_now - timedelta(seconds=30)
    await db_session.flush()

    class SkewedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return db_now + timedelta(days=skew_days)

    monkeypatch.setattr(monitoring, "datetime", SkewedDateTime)
    monkeypatch.setattr(monitor_router, "datetime", SkewedDateTime)
    await monitoring.expire_chargers(db_session)
    await db_session.refresh(charger)
    assert charger.status != "offline"
    scope = build_actor_scope(
        CurrentActor(station.owner_id, frozenset({"station_owner"})), "owned"
    )
    snapshot = await monitoring_snapshot(db_session, scope, MonitorQuery())
    assert snapshot.items[0].online

    before = await monitoring.database_time(db_session)
    await monitoring.mark_seen(db_session, charger.id)
    after = await monitoring.database_time(db_session)
    await db_session.refresh(charger)
    assert before <= charger.last_seen_at <= after

    charger.last_seen_at = db_now - timedelta(seconds=121)
    await db_session.flush()
    await monitoring.expire_chargers(db_session)
    await db_session.refresh(charger)
    await db_session.refresh(connector)
    assert charger.status == "offline" and connector.status == "unknown"
    changed_at = charger.status_updated_at
    await monitoring.expire_chargers(db_session)
    await db_session.refresh(charger)
    assert charger.status_updated_at == changed_at


@pytest.mark.asyncio
async def test_database_time_is_current_even_in_existing_transaction(db_session):
    transaction_time = await db_session.scalar(select(func.now()))
    await db_session.execute(select(func.pg_sleep(0.03)))
    assert await monitoring.database_time(db_session) > transaction_time + timedelta(
        milliseconds=20
    )


@pytest.mark.asyncio
async def test_scan_reads_database_clock_once(db_session, monkeypatch):
    await setup_charger(db_session)
    now = await monitoring.database_time(db_session)
    read_clock = AsyncMock(return_value=now)
    monkeypatch.setattr(monitoring, "database_time", read_clock)
    await monitoring.expire_chargers(db_session)
    read_clock.assert_awaited_once_with(db_session)


@pytest.mark.asyncio
async def test_locked_charger_contact_uses_database_clock(db_session):
    _, charger, _, _ = await setup_charger(db_session)
    before = await monitoring.database_time(db_session)
    await monitoring.mark_seen(db_session, charger.id, locked_charger=charger)
    after = await monitoring.database_time(db_session)
    assert before <= charger.last_seen_at <= after


@pytest.mark.asyncio
async def test_exact_two_intervals_is_live_then_expired(db_session, monkeypatch):
    _, charger, _, _ = await setup_charger(db_session)
    now = await monitoring.database_time(db_session)
    charger.status = "online"
    charger.last_seen_at = now - timedelta(seconds=120)
    await db_session.flush()
    clock = AsyncMock(return_value=now)
    monkeypatch.setattr(monitoring, "database_time", clock)
    await monitoring.expire_chargers(db_session)
    await db_session.refresh(charger)
    assert charger.status == "online"
    clock.return_value = now + timedelta(microseconds=1)
    await monitoring.expire_chargers(db_session)
    await db_session.refresh(charger)
    assert charger.status == "offline"


@pytest.mark.asyncio
async def test_contact_does_not_commit_callers_transaction(db_session):
    _, charger, _, _ = await setup_charger(db_session)
    original = charger.last_seen_at
    nested = await db_session.begin_nested()
    await monitoring.mark_seen(db_session, charger.id)
    await nested.rollback()
    await db_session.refresh(charger)
    assert charger.last_seen_at == original


@pytest.mark.asyncio
async def test_locked_contact_reads_clock_in_single_update(db_session, monkeypatch):
    _, charger, _, _ = await setup_charger(db_session)
    before = await monitoring.database_time(db_session)
    execute = AsyncMock(wraps=db_session.execute)
    monkeypatch.setattr(db_session, "execute", execute)
    await monitoring.mark_seen(db_session, charger.id, locked_charger=charger)
    assert execute.await_count == 1
    await db_session.refresh(charger)
    assert charger.last_seen_at >= before


@pytest.mark.asyncio
async def test_combined_contact_preserves_expiry_and_rollback(db_session):
    _, charger, connector, _ = await setup_charger(db_session)
    now = await monitoring.database_time(db_session)
    charger.last_seen_at = now - timedelta(seconds=121)
    connector.status = "charging"
    await db_session.flush()
    original = charger.last_seen_at
    nested = await db_session.begin_nested()
    recorded = await monitoring.lock_and_mark_seen(db_session, charger.id)
    assert recorded is charger
    assert charger.last_seen_at >= now
    await db_session.refresh(connector)
    assert connector.status == "unknown"
    await nested.rollback()
    await db_session.refresh(charger)
    await db_session.refresh(connector)
    assert charger.last_seen_at == original
    assert connector.status == "charging"
