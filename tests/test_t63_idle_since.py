from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from src.modules.charging.models import ChargingSession
from src.modules.ocpp.dispatcher import process_call
from src.modules.ocpp.frames import Frame, decode_frame
from src.modules.stations.models import ConnectorError
from tests.test_ocpp_monitoring import setup_charger

BASE = datetime(2026, 10, 9, tzinfo=UTC)


async def setup(session):
    _, charger, connector, conn = await setup_charger(session)
    charging = ChargingSession(
        charge_point_id=charger.id,
        connector_id=connector.id,
        tag_tail="ABCD",
        authorization_status="Accepted",
        started_at=BASE,
        meter_start_wh=Decimal(0),
    )
    session.add(charging)
    await session.flush()
    return connector, charging, conn


async def notify(session, conn, status, stamp, connector_id=1, error="NoError"):
    payload = {"connectorId": connector_id, "status": status, "errorCode": error}
    if stamp is not None:
        payload["timestamp"] = stamp.isoformat()
    reply = await process_call(
        conn, Frame(2, str(uuid4()), payload, action="StatusNotification"), session
    )
    assert decode_frame(reply).kind == 3


@pytest.mark.asyncio
async def test_final_idle_interval_and_source_clock(db_session):
    connector, charging, conn = await setup(db_session)
    first, resumed, last = [BASE + timedelta(minutes=i) for i in (1, 2, 3)]
    await notify(db_session, conn, "SuspendedEV", first)
    await db_session.refresh(charging)
    assert charging.idle_since == first
    await notify(db_session, conn, "SuspendedEV", first + timedelta(seconds=1))
    await db_session.refresh(charging)
    assert charging.idle_since == first
    await notify(db_session, conn, "Charging", resumed)
    await db_session.refresh(charging)
    assert charging.idle_since is None
    await notify(db_session, conn, "SuspendedEV", last)
    await db_session.refresh(charging)
    await db_session.refresh(connector)
    assert charging.idle_since == last
    assert connector.last_status_notification_at == last
    assert abs((connector.status_updated_at - datetime.now(UTC)).total_seconds()) < 5


@pytest.mark.asyncio
@pytest.mark.parametrize("late_status", ["SuspendedEV", "Charging", "Faulted"])
async def test_late_and_replayed_notifications_cannot_overwrite(
    db_session, late_status
):
    connector, charging, conn = await setup(db_session)
    latest = BASE + timedelta(minutes=3)
    await notify(db_session, conn, "SuspendedEV", latest)
    await db_session.refresh(connector)
    updated = connector.status_updated_at
    for stamp in (latest - timedelta(minutes=1), latest):
        await notify(db_session, conn, late_status, stamp, error="GroundFailure")
    await db_session.refresh(charging)
    await db_session.refresh(connector)
    assert charging.idle_since == latest
    assert connector.status == "SuspendedEV"
    assert connector.last_status_notification_at == latest
    assert connector.status_updated_at == updated
    assert (
        await db_session.scalar(select(func.count()).select_from(ConnectorError)) == 0
    )


@pytest.mark.asyncio
async def test_old_suspension_after_charging_does_not_restart_idle(db_session):
    connector, charging, conn = await setup(db_session)
    await notify(db_session, conn, "SuspendedEV", BASE + timedelta(minutes=1))
    await notify(db_session, conn, "Charging", BASE + timedelta(minutes=2))
    await notify(db_session, conn, "SuspendedEV", BASE + timedelta(minutes=1))
    await db_session.refresh(charging)
    await db_session.refresh(connector)
    assert charging.idle_since is None
    assert connector.status == "Charging"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status", ["SuspendedEVSE", "Finishing", "Available", "Faulted"]
)
async def test_other_statuses_do_not_start_idle(db_session, status):
    _, charging, conn = await setup(db_session)
    await notify(db_session, conn, status, BASE + timedelta(minutes=1))
    await db_session.refresh(charging)
    assert charging.idle_since is None


@pytest.mark.asyncio
async def test_finishing_preserves_last_idle_interval(db_session):
    _, charging, conn = await setup(db_session)
    stamp = BASE + timedelta(minutes=1)
    await notify(db_session, conn, "SuspendedEV", stamp)
    await notify(db_session, conn, "Finishing", stamp + timedelta(minutes=1))
    await db_session.refresh(charging)
    assert charging.idle_since == stamp


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["SuspendedEV", "Charging"])
async def test_missing_timestamp_preserves_idle_and_watermark(db_session, status):
    connector, charging, conn = await setup(db_session)
    stamp = BASE + timedelta(minutes=1)
    await notify(db_session, conn, "SuspendedEV", stamp)
    await notify(db_session, conn, status, None)
    await db_session.refresh(charging)
    await db_session.refresh(connector)
    assert charging.idle_since == stamp
    assert connector.last_status_notification_at == stamp
    assert connector.status == status


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["SuspendedEV", "Charging"])
async def test_closed_session_not_modified(db_session, status):
    _, charging, conn = await setup(db_session)
    charging.idle_since = BASE + timedelta(minutes=1)
    charging.ended_at = BASE + timedelta(minutes=2)
    await db_session.flush()
    await notify(db_session, conn, status, BASE + timedelta(minutes=3))
    await db_session.refresh(charging)
    assert charging.idle_since == BASE + timedelta(minutes=1)


@pytest.mark.asyncio
@pytest.mark.parametrize("connector_id", [0, 99])
async def test_other_connector_does_not_start_idle(db_session, connector_id):
    _, charging, conn = await setup(db_session)
    await notify(
        db_session, conn, "SuspendedEV", BASE + timedelta(minutes=1), connector_id
    )
    await db_session.refresh(charging)
    assert charging.idle_since is None


@pytest.mark.asyncio
async def test_pre_session_notification_cannot_start_idle(db_session):
    _, charging, conn = await setup(db_session)
    await notify(db_session, conn, "SuspendedEV", BASE - timedelta(seconds=1))
    await db_session.refresh(charging)
    assert charging.idle_since is None


@pytest.mark.asyncio
async def test_no_open_session_still_updates_connector(db_session):
    _, _, connector, conn = await setup_charger(db_session)
    await notify(db_session, conn, "SuspendedEV", BASE)
    await db_session.refresh(connector)
    assert connector.status == "SuspendedEV"
    assert connector.last_status_notification_at == BASE


@pytest.mark.asyncio
async def test_missing_timestamp_cannot_start_idle(db_session):
    connector, charging, conn = await setup(db_session)
    await notify(db_session, conn, "SuspendedEV", None)
    await db_session.refresh(charging)
    await db_session.refresh(connector)
    assert charging.idle_since is None
    assert connector.last_status_notification_at is None


@pytest.mark.asyncio
async def test_timezone_and_microseconds_preserved(db_session):
    from datetime import timezone

    _, charging, conn = await setup(db_session)
    stamp = (BASE + timedelta(minutes=1, microseconds=123456)).astimezone(
        timezone(timedelta(hours=5, minutes=30))
    )
    await notify(db_session, conn, "SuspendedEV", stamp)
    await db_session.refresh(charging)
    assert charging.idle_since == stamp
    assert charging.idle_since.microsecond == 123456
