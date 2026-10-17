"""Committed PostgreSQL acceptance for the original S-59 events and delivery."""

import asyncio
import sys
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, update

from src.entrypoints.http import app
from src.modules.billing.invoicing import lap_hoa_don
from src.modules.charging.models import ChargingSession, OccupationInterval
from src.modules.charging.payloads import StopPayload
from src.modules.charging.service import stop_transaction
from src.modules.driver_notifications import worker
from src.modules.driver_notifications.models import DriverNotification as Notice
from src.modules.driver_notifications.service import notify_event, scan_idle
from src.modules.identity.authorization import CurrentActor
from src.modules.identity.dependencies import get_current_actor
from src.modules.identity.models import User
from src.modules.ocpp.frames import Frame
from src.modules.stations.models import ChargePoint
from src.platform.database import session as database_session
from src.platform.database.session import SessionFactory
from tests.test_t80_invoicing import seed
from tests.test_wallet_service import isolated_wallet_db  # noqa: F401


@pytest.fixture(autouse=True)
async def isolated_notifications(isolated_wallet_db, monkeypatch):  # noqa: F811
    monkeypatch.setattr(sys.modules[__name__], "SessionFactory", isolated_wallet_db)
    monkeypatch.setattr(worker, "SessionFactory", isolated_wallet_db)
    monkeypatch.setattr(database_session, "SessionFactory", isolated_wallet_db)


async def prepared(*, idle_minutes=6, released=False):
    now = datetime.now(UTC)
    async with SessionFactory() as db, db.begin():
        charging, _station, driver, _version = await seed(
            db, stamp=now - timedelta(hours=1), duration=timedelta(minutes=50)
        )
        charging.billing_lifecycle_version = 1
        charging.connector_released_at = now if released else None
        interval = OccupationInterval(
            session_id=charging.id,
            started_at=now - timedelta(minutes=idle_minutes),
            confirmed=True,
            ended_at=now if released else None,
            end_reason="released" if released else None,
        )
        db.add(interval)
        await db.flush()
        return charging.id, driver.id, now


async def notices(session_id):
    async with SessionFactory() as db:
        return list(
            await db.scalars(
                select(Notice)
                .where(Notice.session_id == session_id)
                .order_by(Notice.occurred_at)
            )
        )


async def test_real_stop_transaction_commits_one_stop_intent_and_amount():
    sid, _uid, now = await prepared()
    async with SessionFactory() as db, db.begin():
        charging = await db.get(ChargingSession, sid)
        charger = await db.get(ChargePoint, charging.charge_point_id)
        charging.ended_at = None
        charging.meter_stop_wh = None
        charging.energy_kwh = None
        await db.flush()
        # An accepted remote command alone has no stop event to publish.
        await notify_event(db, charging, "stop")
        assert (
            await db.scalar(
                select(func.count()).select_from(Notice).where(Notice.session_id == sid)
            )
            == 0
        )
        payload = StopPayload.model_validate(
            {
                "transactionId": sid,
                "meterStop": 1000,
                "timestamp": now - timedelta(minutes=8),
                "reason": "Remote",
            }
        )
        frame = Frame(2, str(uuid4()), {}, action="StopTransaction")
        for _ in range(5):
            await stop_transaction(db, charger, frame, payload)
    rows = await notices(sid)
    assert len(rows) == 1 and rows[0].event_type == "stop"
    assert "1.000000 kWh" in rows[0].message and "3,000" in rows[0].message
    assert "chưa chốt" in rows[0].message and rows[0].email_status == "pending"


async def test_stop_idle_invoice_are_distinct_durable_and_replay_safe():
    sid, uid, now = await prepared()
    async with SessionFactory() as db, db.begin():
        charging = await db.get(ChargingSession, sid)
        for _ in range(5):
            await notify_event(db, charging, "stop")
        await scan_idle(db, now)
    async with SessionFactory() as db, db.begin():
        await scan_idle(db, now + timedelta(seconds=1))
        charging = await db.get(ChargingSession, sid)
        charging.connector_released_at = now
        interval = await db.scalar(
            select(OccupationInterval).where(OccupationInterval.session_id == sid)
        )
        interval.ended_at = now
        interval.end_reason = "released"
        for _ in range(5):
            result = await lap_hoa_don(db, sid)
            assert result.status == "ready"
    rows = await notices(sid)
    assert [r.event_type for r in rows] == ["stop", "idle", "invoice"]
    assert rows[0].driver_id == uid
    assert "chưa chốt" in rows[0].message
    assert "Phí" not in rows[0].title
    assert "phí chiếm trụ" in rows[1].title
    assert f"{result.invoice.total_vnd:,}" in rows[2].message
    assert "đã chốt" in rows[2].message


@pytest.mark.parametrize("minutes", [0, 3, 5])
async def test_unplug_before_or_at_grace_has_no_idle_notice(minutes):
    sid, _, now = await prepared(idle_minutes=minutes, released=True)
    async with SessionFactory() as db, db.begin():
        await scan_idle(db, now + timedelta(minutes=10))
        result = await lap_hoa_don(db, sid)
        assert result.status == "ready"
    assert [row.event_type for row in await notices(sid)] == ["invoice"]


async def test_pending_invoice_never_announces_financial_completion():
    sid, _, _ = await prepared()
    async with SessionFactory() as db, db.begin():
        result = await lap_hoa_don(db, sid)
        assert result.status == "pending"
    assert await notices(sid) == []


async def test_rollback_leaves_neither_inbox_nor_email_intent():
    sid, _, _ = await prepared()
    async with SessionFactory() as db:
        charging = await db.get(ChargingSession, sid)
        await notify_event(db, charging, "stop")
        await db.rollback()
    assert await notices(sid) == []


async def test_retry_and_expired_lease_keep_message_id_without_duplicate_intents(
    monkeypatch,
):
    sid, _uid, now = await prepared()
    async with SessionFactory() as db, db.begin():
        await notify_event(db, await db.get(ChargingSession, sid), "stop")
    async with SessionFactory() as db, db.begin():
        await db.execute(
            update(Notice)
            .where(Notice.session_id == sid)
            .values(next_attempt_at=datetime(1970, 1, 1, tzinfo=UTC))
        )
    monkeypatch.setattr(worker, "smtp_enabled", lambda: True)
    sender = Mock(side_effect=OSError("SMTP offline"))
    monkeypatch.setattr(worker, "send_email", sender)
    await worker.deliver_one()
    row = (await notices(sid))[0]
    assert row.email_status == "pending" and row.attempts == 1
    async with SessionFactory() as db, db.begin():
        await db.execute(
            update(Notice)
            .where(Notice.id == row.id)
            .values(
                email_status="sending",
                lease_until=now - timedelta(seconds=1),
                next_attempt_at=datetime(1970, 1, 1, tzinfo=UTC),
            )
        )
    sender.side_effect = None
    await worker.deliver_one()
    row = (await notices(sid))[0]
    assert row.email_status == "sent" and row.attempts == 2
    assert (
        sender.call_args_list[0].kwargs["message_id"]
        == sender.call_args_list[1].kwargs["message_id"]
    )
    assert sender.call_args.kwargs["recipient"]


async def test_inbox_ownership_read_persistence_and_role_policy():
    sid, uid, _ = await prepared()
    async with SessionFactory() as db, db.begin():
        await notify_event(db, await db.get(ChargingSession, sid), "stop")
    row = (await notices(sid))[0]
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        try:
            app.dependency_overrides[get_current_actor] = lambda: CurrentActor(
                uid, frozenset({"driver"})
            )
            first = await client.get("/api/v1/driver/notifications")
            assert first.status_code == 200 and any(
                r["id"] == str(row.id) for r in first.json()["items"]
            )
            assert (
                await client.post(f"/api/v1/driver/notifications/{row.id}/read")
            ).status_code == 200
            assert next(
                r
                for r in (await client.get("/api/v1/driver/notifications")).json()[
                    "items"
                ]
                if r["id"] == str(row.id)
            )["read_at"]
            app.dependency_overrides[get_current_actor] = lambda: CurrentActor(
                uuid4(), frozenset({"driver"})
            )
            assert (await client.get("/api/v1/driver/notifications")).json()[
                "items"
            ] == []
            assert (
                await client.post(f"/api/v1/driver/notifications/{row.id}/read")
            ).status_code == 404
            app.dependency_overrides[get_current_actor] = lambda: CurrentActor(
                uid, frozenset({"operator"})
            )
            assert (await client.get("/api/v1/driver/notifications")).status_code == 403
        finally:
            app.dependency_overrides.pop(get_current_actor, None)


async def test_privacy_freeze_purges_location_text_and_prevents_recreation():
    sid, uid, _ = await prepared()
    async with SessionFactory() as db, db.begin():
        charging = await db.get(ChargingSession, sid)
        await notify_event(db, charging, "stop")
        user = await db.get(User, uid)
        user.status = "pending_deletion"
        await db.flush()
        await notify_event(db, charging, "stop")
    assert await notices(sid) == []


async def test_actual_background_loop_recovers_pending_email_and_stops_cleanly(
    monkeypatch,
):
    sid, _, _ = await prepared()
    async with SessionFactory() as db, db.begin():
        await notify_event(db, await db.get(ChargingSession, sid), "stop")
    sender = Mock()
    monkeypatch.setattr(worker, "smtp_enabled", lambda: True)
    monkeypatch.setattr(worker, "send_email", sender)
    monkeypatch.setattr(worker.settings, "driver_notifications_enabled", True)
    task = asyncio.create_task(worker.notification_loop())
    try:
        async with asyncio.timeout(10):
            while not any(
                row.event_type == "stop" and row.email_status == "sent"
                for row in await notices(sid)
            ):
                await asyncio.sleep(0.05)
        assert sender.called
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_missing_tariff_reports_unknown_instead_of_zero_money():
    async with SessionFactory() as db, db.begin():
        charging, _, _, _ = await seed(
            db, stamp=datetime.now(UTC) - timedelta(hours=1), with_tariff=False
        )
        await notify_event(db, charging, "stop")
        sid = charging.id
    row = (await notices(sid))[0]
    assert "đang đối chiếu" in row.message and "0 đ" not in row.message


async def test_expired_inbox_is_removed_and_old_event_replay_is_not_recreated():
    sid, _, _ = await prepared()
    async with SessionFactory() as db, db.begin():
        charging = await db.get(ChargingSession, sid)
        await notify_event(db, charging, "stop")
        await db.execute(
            update(Notice)
            .where(Notice.session_id == sid)
            .values(created_at=datetime.now(UTC) - timedelta(days=91))
        )
    await worker.scan_tick()
    assert not any(row.event_type == "stop" for row in await notices(sid))
    async with SessionFactory() as db, db.begin():
        charging = await db.get(ChargingSession, sid)
        charging.ended_at = datetime.now(UTC) - timedelta(days=91)
        await notify_event(db, charging, "stop")
    assert not any(row.event_type == "stop" for row in await notices(sid))
