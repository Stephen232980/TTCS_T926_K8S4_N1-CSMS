"""S-46 PostgreSQL episodes, ownership, real SMTP and recovery after failure."""

import asyncio
import smtplib
import socketserver
import subprocess
import sys
import threading
from datetime import UTC, datetime, timedelta
from email import policy
from email.parser import BytesParser
from time import monotonic
from types import SimpleNamespace
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from src.config import Settings, settings
from src.entrypoints.http import app
from src.modules.alerts import worker
from src.modules.alerts.models import AlertEmail, OperationalAlert
from src.modules.alerts.service import scan_alerts
from src.modules.identity.authorization import CurrentActor
from src.modules.identity.dependencies import get_current_actor
from src.modules.ocpp.connection_registry import OcppConnection
from src.modules.ocpp.dispatcher import process_call
from src.modules.ocpp.frames import Frame
from src.modules.stations.models import ChargePoint, Connector, ConnectorError
from tests.test_flat_tariff_api import api_db, committed_tariff_db  # noqa: F401
from tests.test_tariff_schema import make_station


@pytest.fixture
async def alert_fleet(api_db, monkeypatch):  # noqa: F811
    monkeypatch.setattr(settings, "alert_email_recipients", ["ops@example.com"])
    monkeypatch.setattr(settings, "alert_smtp_enabled", True)
    monkeypatch.setattr(settings, "alert_smtp_host", "127.0.0.1")
    monkeypatch.setattr(settings, "alert_smtp_from", "csms@example.com")
    monkeypatch.setattr(worker, "SessionFactory", api_db)
    now = datetime.now(UTC)
    async with api_db() as db, db.begin():
        station = await make_station(db)
        station.status = "active"
        point = ChargePoint(
            station_id=station.id,
            code=f"ALERT-{uuid4().hex[:8]}",
            status="offline",
            last_seen_at=now - timedelta(minutes=10),
            last_boot_at=now - timedelta(hours=1),
            heartbeat_interval_seconds=60,
        )
        db.add(point)
        await db.flush()
        connector = Connector(
            charge_point_id=point.id, connector_number=1, status="unknown"
        )
        db.add(connector)
        await db.flush()
    yield api_db, station, point, connector, now
    app.dependency_overrides.pop(get_current_actor, None)


async def scan(factory, now):
    async with factory() as db, db.begin():
        return await scan_alerts(db, now)


async def test_offline_threshold_atomic_outbox_and_single_active_alert(alert_fleet):
    factory, _, point, _, now = alert_fleet
    boundary = point.last_seen_at + timedelta(seconds=420)
    assert await scan(factory, boundary - timedelta(microseconds=1)) == 0
    assert await scan(factory, boundary) == 1
    assert await scan(factory, now) == 0
    async with factory() as db:
        assert await db.scalar(select(func.count()).select_from(OperationalAlert)) == 1
        assert await db.scalar(select(func.count()).select_from(AlertEmail)) == 1
        alert = await db.scalar(select(OperationalAlert))
        with pytest.raises(IntegrityError):
            db.add(
                OperationalAlert(
                    charge_point_id=point.id, kind="error_burst", opened_at=now
                )
            )
            await db.flush()
        await db.rollback()
        assert alert is not None


async def test_concurrent_scanners_do_not_duplicate_alerts(alert_fleet):
    factory, _, _, _, now = alert_fleet
    results = await asyncio.gather(*(scan(factory, now) for _ in range(10)))
    assert sum(results) == 1
    async with factory() as db:
        assert await db.scalar(select(func.count()).select_from(AlertEmail)) == 1


async def test_ocpp_replay_counts_one_error_then_distinct_messages_open_burst(
    alert_fleet,
):
    factory, station, point, _, now = alert_fleet
    connection = OcppConnection(
        point.id,
        station.id,
        point.code,
        "active",
        SimpleNamespace(),
        now,
        boot_accepted=True,
    )
    frame = Frame(
        2,
        str(uuid4()),
        {"connectorId": 1, "status": "Faulted", "errorCode": "OtherError"},
        "StatusNotification",
    )
    async with factory() as db, db.begin():
        live = await db.get(ChargePoint, point.id)
        live.status, live.last_seen_at = "online", now
        for _ in range(5):
            await process_call(connection, frame, db)
    async with factory() as db:
        assert await db.scalar(select(func.count()).select_from(ConnectorError)) == 1
    assert await scan(factory, datetime.now(UTC)) == 0
    async with factory() as db, db.begin():
        for _ in range(2):
            await process_call(
                connection, Frame(2, str(uuid4()), frame.payload, frame.action), db
            )
    assert await scan(factory, datetime.now(UTC)) == 1
    async with factory() as db:
        alert = await db.scalar(select(OperationalAlert))
        assert alert.kind == "error_burst"
        assert alert.details["error_count"] == 3
        assert "idTag" not in str(alert.details)


async def test_alert_permissions_ownership_ack_and_close_guards(alert_fleet):
    factory, station, _, _, now = alert_fleet
    await scan(factory, now)
    async with factory() as db:
        alert_id = (await db.scalar(select(OperationalAlert))).id
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        assert (await client.get("/api/v1/ops/alerts")).status_code == 401
        for role in ("driver", "accountant", "station_owner"):
            app.dependency_overrides[get_current_actor] = lambda r=role: CurrentActor(
                station.owner_id, frozenset({r})
            )
            assert (await client.get("/api/v1/ops/alerts")).status_code == 403
        app.dependency_overrides[get_current_actor] = lambda: CurrentActor(
            station.owner_id, frozenset({"station_owner"})
        )
        response = await client.get("/api/v1/owner/alerts")
        assert response.status_code == 200 and response.json()["total"] == 1
        assert "ops@example.com" not in response.text
        app.dependency_overrides[get_current_actor] = lambda: CurrentActor(
            uuid4(), frozenset({"station_owner"})
        )
        assert (await client.get("/api/v1/owner/alerts")).json()["total"] == 0
        app.dependency_overrides[get_current_actor] = lambda: CurrentActor(
            station.owner_id, frozenset({"operator"})
        )
        assert (
            await client.post(f"/api/v1/ops/alerts/{alert_id}/acknowledge")
        ).status_code == 200
        assert (
            await client.post(f"/api/v1/ops/alerts/{alert_id}/acknowledge")
        ).status_code == 200
        assert (
            await client.post(f"/api/v1/ops/alerts/{alert_id}/close", json={})
        ).status_code == 409
        assert (
            await client.post(
                f"/api/v1/ops/alerts/{alert_id}/close",
                json={"force": True, "reason": "maintenance"},
            )
        ).status_code == 403
        app.dependency_overrides[get_current_actor] = lambda: CurrentActor(
            station.owner_id, frozenset({"admin"})
        )
        assert (
            await client.post(
                f"/api/v1/admin/alerts/{alert_id}/close", json={"force": True}
            )
        ).status_code == 422
        assert (
            await client.post(
                f"/api/v1/admin/alerts/{alert_id}/close",
                json={"force": True, "reason": "maintenance"},
            )
        ).status_code == 200
    assert await scan(factory, now + timedelta(seconds=15)) == 0
    async with factory() as db:
        alert = await db.get(OperationalAlert, alert_id)
        assert (
            alert.acknowledged_by == station.owner_id
            and alert.closed_by == station.owner_id
        )
        assert alert.close_reason == "maintenance"
        assert await db.scalar(select(func.count()).select_from(OperationalAlert)) == 1


async def test_recovery_requires_stability_and_quiet_then_new_episode(alert_fleet):
    factory, station, point, _, now = alert_fleet
    await scan(factory, now - timedelta(minutes=2))
    async with factory() as db, db.begin():
        live = await db.get(ChargePoint, point.id)
        live.status, live.last_seen_at = "online", now - timedelta(minutes=2)
    await scan(factory, now - timedelta(minutes=2))
    async with factory() as db:
        assert (await db.scalar(select(OperationalAlert))).recovered_at is None
    async with factory() as db, db.begin():
        (await db.get(ChargePoint, point.id)).last_seen_at = now
    await scan(factory, now)
    async with factory() as db:
        alert = await db.scalar(select(OperationalAlert))
        assert alert.recovered_at == now
        alert_id = alert.id
    app.dependency_overrides[get_current_actor] = lambda: CurrentActor(
        station.owner_id, frozenset({"operator"})
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        assert (
            await client.post(f"/api/v1/ops/alerts/{alert_id}/close", json={})
        ).status_code == 200
    assert await scan(factory, now + timedelta(seconds=421)) == 1
    async with factory() as db:
        assert await db.scalar(select(func.count()).select_from(OperationalAlert)) == 2


async def test_restart_lease_retry_and_permanent_failure_keep_one_email(
    alert_fleet, monkeypatch
):
    factory, _, _, _, now = alert_fleet
    await scan(factory, now)
    first, other = await asyncio.gather(worker.claim_emails(), worker.claim_emails())
    assert len(first) + len(other) == 1
    delivery = (first or other)[0]
    async with factory() as db, db.begin():
        email = await db.get(AlertEmail, delivery.id)
        email.locked_until = now - timedelta(seconds=1)
    resumed = (await worker.claim_emails())[0]
    assert resumed.id == delivery.id and resumed.lease_token != delivery.lease_token

    def fail(_delivery):
        raise smtplib.SMTPException("must not leak server response or credentials")

    monkeypatch.setattr(worker, "send_smtp", fail)
    await worker.deliver_email(resumed)
    async with factory() as db, db.begin():
        email = await db.get(AlertEmail, delivery.id)
        assert email.status == "retry" and email.last_error == "smtp_unavailable"
        assert email.next_attempt_at > now
        email.attempts = settings.alert_email_max_attempts - 1
        email.next_attempt_at = now - timedelta(seconds=1)
    await worker.deliver_email((await worker.claim_emails())[0])
    async with factory() as db:
        email = await db.get(AlertEmail, delivery.id)
        assert email.status == "failed"
        assert await db.scalar(select(func.count()).select_from(AlertEmail)) == 1
        assert (await db.scalar(select(OperationalAlert))).status == "open"


@pytest.mark.parametrize("shared_profile", [False, True])
async def test_smtp_actual_delivery_has_stable_message_id_without_driver_data(
    alert_fleet, monkeypatch, shared_profile
):
    factory, station, _, _, now = alert_fleet
    received = []

    class Handler(socketserver.StreamRequestHandler):
        def handle(self):
            self.wfile.write(b"220 localhost test SMTP\r\n")
            while raw := self.rfile.readline():
                command = raw.decode().strip().upper()
                if command == "DATA":
                    self.wfile.write(b"354 send data\r\n")
                    lines = []
                    while (line := self.rfile.readline()) != b".\r\n":
                        if not line:
                            return
                        lines.append(line)
                    received.append(b"".join(lines))
                    self.wfile.write(b"250 accepted\r\n")
                elif command == "QUIT":
                    self.wfile.write(b"221 bye\r\n")
                    return
                else:
                    self.wfile.write(b"250 OK\r\n")

    with socketserver.ThreadingTCPServer(("127.0.0.1", 0), Handler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        monkeypatch.setattr(settings, "alert_smtp_security", "plain")
        monkeypatch.setattr(settings, "alert_smtp_port", server.server_address[1])
        if shared_profile:
            monkeypatch.setattr(settings, "smtp_enabled", True)
            monkeypatch.setattr(settings, "smtp_host", "127.0.0.1")
            monkeypatch.setattr(settings, "smtp_from", "csms@example.com")
            monkeypatch.setattr(settings, "smtp_security", "plain")
            monkeypatch.setattr(settings, "smtp_port", server.server_address[1])
        try:
            await scan(factory, now)
            delivery = (await worker.claim_emails())[0]
            await worker.deliver_email(delivery)
            assert len(received) == 1
            message = BytesParser(policy=policy.default).parsebytes(received[0])
            assert message["Message-ID"] == f"<csms-alert-{delivery.id}@csms.invalid>"
            assert station.name in message.get_content()
            assert (
                "idTag" not in message.get_content()
                and "driver" not in message.get_content()
            )
            async with factory() as db:
                assert (await db.get(AlertEmail, delivery.id)).status == "sent"
            assert not await worker.claim_emails()
        finally:
            server.shutdown()
            thread.join(timeout=2)


async def test_fifty_offline_chargers_scan_under_poll_budget(alert_fleet):
    factory, station, point, _, now = alert_fleet
    async with factory() as db, db.begin():
        for index in range(49):
            db.add(
                ChargePoint(
                    station_id=station.id,
                    code=f"FLEET50-{uuid4().hex[:8]}-{index}",
                    last_seen_at=point.last_seen_at,
                    heartbeat_interval_seconds=60,
                )
            )
    started = monotonic()
    assert await scan(factory, now) == 50
    elapsed = monotonic() - started
    assert elapsed < 5  # scanner 15s + UI 10s + this scan fit the 30s target.
    async with factory() as db:
        assert await db.scalar(select(func.count()).select_from(AlertEmail)) == 50
    assert await scan(factory, now + timedelta(seconds=15)) == 0
    print(f"G3 scan 50 chargers: {elapsed:.3f}s")


async def test_alert_migration_roundtrip_keeps_station(alert_fleet):
    import os

    from src.modules.stations.models import Station

    factory, station, _, _, _ = alert_fleet
    url = factory.kw["bind"].url.render_as_string(hide_password=False)
    for command in (["downgrade", "a210021a2026"], ["upgrade", "head"]):
        await asyncio.to_thread(
            subprocess.run,
            [sys.executable, "-m", "alembic", *command],
            env=os.environ | {"DATABASE_URL": url},
            check=True,
            capture_output=True,
        )
    async with factory() as db:
        assert (await db.get(Station, station.id)).name == station.name


@pytest.mark.parametrize(
    "options",
    [
        {"alert_offline_grace_seconds": 0},
        {"alert_error_threshold": 1},
        {"alert_scan_interval_seconds": 16},
        {"alert_smtp_enabled": True},
        {"alert_smtp_username": "without-password"},
    ],
)
def test_thresholds_and_smtp_config_are_validated(options):
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Settings(_env_file=None, **options)


def test_disabled_smtp_accepts_empty_compose_environment_values():
    configured = Settings(
        _env_file=None,
        alert_smtp_enabled=False,
        alert_smtp_from="",
        alert_smtp_password="",
        alert_smtp_username="",
    )
    assert configured.alert_smtp_from is None and configured.alert_smtp_password is None


async def test_alert_list_clamps_page_when_totals_shrink(alert_fleet):
    factory, station, _, _, now = alert_fleet
    await scan(factory, now)
    app.dependency_overrides[get_current_actor] = lambda: CurrentActor(
        station.owner_id, frozenset({"operator"})
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/api/v1/ops/alerts?page=2")
        assert response.status_code == 200
        assert response.json()["page"] == 1 and response.json()["total"] == 1
        assert len(response.json()["items"]) == 1


async def test_retry_email_keeps_identity_and_sent_deliveries(alert_fleet):
    factory, station, _, _, now = alert_fleet
    await scan(factory, now)
    async with factory() as db, db.begin():
        email = await db.scalar(select(AlertEmail))
        email.status, email.attempts, email.last_error = "failed", 6, "smtp_unavailable"
        email_id, alert_id = email.id, email.alert_id
    app.dependency_overrides[get_current_actor] = lambda: CurrentActor(
        station.owner_id, frozenset({"operator"})
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        for _ in range(2):
            assert (
                await client.post(f"/api/v1/ops/alerts/{alert_id}/retry-email")
            ).status_code == 200
    async with factory() as db, db.begin():
        email = await db.get(AlertEmail, email_id)
        assert email.status == "pending" and email.attempts == 0
        assert email.last_error is None
        assert await db.scalar(select(func.count()).select_from(AlertEmail)) == 1
        email.status = "sent"
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        assert (
            await client.post(f"/api/v1/ops/alerts/{alert_id}/retry-email")
        ).status_code == 200
    async with factory() as db:
        assert (await db.get(AlertEmail, email_id)).status == "sent"
