from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import func, select

from src.entrypoints.http import app
from src.modules.charging import driver as driver_service
from src.modules.charging import service as charging_service
from src.modules.charging.driver import expire_start_requests, remote_start, virtual_tag
from src.modules.charging.driver_models import DriverStartRequest, DriverVirtualTag
from src.modules.charging.models import ChargingCard, ChargingSession
from src.modules.identity.authorization import CurrentActor
from src.modules.identity.dependencies import get_current_actor
from src.modules.ocpp import control
from src.modules.ocpp.connection_registry import ocpp_connections
from src.modules.ocpp.control_models import ControlRequest
from src.modules.ocpp.frames import decode_frame
from src.modules.stations.models import Station
from src.modules.wallet.models import DriverWallet
from tests.test_charging_sessions import call, meter_payload, setup, start
from tests.test_ocpp_control import db_session as control_database
from tests.test_ocpp_control import reply_with

db_session = control_database


@pytest.mark.parametrize(
    ("balance_vnd", "price_vnd_per_kwh", "eligible"),
    [
        (Decimal("15000"), Decimal("1000"), True),
        (Decimal("14999"), Decimal("1000"), False),
        (Decimal("16000"), Decimal("1200"), True),
        (Decimal("15000"), Decimal("1200"), False),
    ],
)
def test_du_so_du_de_sac_uses_station_price(
    balance_vnd: Decimal, price_vnd_per_kwh: Decimal, eligible: bool
) -> None:
    station = Station(price_vnd_per_kwh=price_vnd_per_kwh)

    assert charging_service.du_so_du_de_sac(balance_vnd, station) is eligible


def test_du_so_du_de_sac_rejects_missing_balance_or_station_price() -> None:
    assert not charging_service.du_so_du_de_sac(None, Station(price_vnd_per_kwh=1000))
    assert not charging_service.du_so_du_de_sac(Decimal("50000"), Station())


async def test_remote_start_rejects_insufficient_wallet_before_sending(
    db_session, fixture
):
    _, _, connector, driver, _, conn, _ = fixture
    wallet = await db_session.scalar(
        select(DriverWallet).where(DriverWallet.driver_id == driver.id)
    )
    assert wallet is not None
    wallet.balance_vnd = Decimal("14999")
    await db_session.commit()

    with pytest.raises(HTTPException) as error:
        await remote_start(driver.id, uuid4(), connector.id)

    assert error.value.status_code == 409
    assert "Số dư ví không đủ" in error.value.detail
    conn.websocket.send_text.assert_not_awaited()


@pytest_asyncio.fixture
async def fixture(db_session, monkeypatch):
    monkeypatch.setattr(driver_service, "SessionFactory", control.SessionFactory)
    station, charger, connector, driver, card, conn, tag = await setup(db_session)
    charger.last_seen_at = datetime.now(UTC)
    charger.code = charger.code.upper()
    conn.charge_point_code = charger.code.lower()
    await db_session.commit()
    await ocpp_connections.replace(conn)
    yield station, charger, connector, driver, card, conn, tag
    await ocpp_connections.remove(conn.charge_point_code, conn.websocket)


@pytest.mark.parametrize("outcome", ["Accepted", "Rejected", "Invalid"])
async def test_start_reply_reuse_virtual_tag_and_safe_audit(
    db_session, fixture, outcome
):
    _, charger, connector, driver, _, conn, _ = fixture
    reply_with(conn, outcome)
    key = uuid4()
    result = await remote_start(driver.id, key, connector.id)
    assert result["status"] == (outcome if outcome != "Invalid" else "ProtocolError")
    assert result["session_id"] is None
    assert await remote_start(driver.id, key, connector.id) == result
    assert conn.websocket.send_text.await_count == 1
    frame = decode_frame(conn.websocket.send_text.call_args.args[0])
    assert frame.action == "RemoteStartTransaction"
    assert frame.payload["connectorId"] == 1
    raw = frame.payload["idTag"]
    assert len(raw) == 20
    await db_session.refresh(driver)
    assert await virtual_tag(db_session, driver) == raw
    assert (
        await db_session.scalar(select(func.count()).select_from(DriverVirtualTag)) == 1
    )
    request = await db_session.get(ControlRequest, key)
    assert request.payload == {"connectorId": 1}
    assert request.actor_id == driver.id
    assert request.charge_point_code == charger.code
    assert (
        await db_session.scalar(select(func.count()).select_from(ChargingSession)) == 0
    )


@pytest.mark.parametrize(
    "status", ["Charging", "Reserved", "Faulted", "Unavailable", "Unknown"]
)
async def test_busy_connector_rejected_before_send(db_session, fixture, status):
    _, _, connector, driver, _, conn, _ = fixture
    connector.status = status
    await db_session.commit()
    with pytest.raises(HTTPException) as error:
        await remote_start(driver.id, uuid4(), connector.id)
    assert error.value.status_code == 409
    conn.websocket.send_text.assert_not_awaited()


async def test_active_driver_and_pending_start_block_duplicate(db_session, fixture):
    _, _, connector, driver, _, conn, tag = fixture
    reply_with(conn)
    await remote_start(driver.id, uuid4(), connector.id)
    with pytest.raises(HTTPException):
        await remote_start(driver.id, uuid4(), connector.id)
    assert conn.websocket.send_text.await_count == 1
    await expire_start_requests(db_session, datetime.now(UTC) + timedelta(seconds=61))
    await start(db_session, conn, tag)
    await db_session.commit()
    with pytest.raises(HTTPException):
        await remote_start(driver.id, uuid4(), connector.id)
    assert conn.websocket.send_text.await_count == 1


@pytest.mark.parametrize("scenario", ["offline", "timeout", "disconnect"])
async def test_unavailable_start_does_not_create_session(
    db_session, fixture, monkeypatch, scenario
):
    _, _, connector, driver, _, conn, _ = fixture
    if scenario == "offline":
        await ocpp_connections.remove(conn.charge_point_code, conn.websocket)
    elif scenario == "timeout":
        monkeypatch.setattr(control, "COMMAND_TIMEOUT", 0.02)
    else:
        conn.websocket.send_text = AsyncMock(side_effect=ConnectionError())
    result = await remote_start(driver.id, uuid4(), connector.id)
    assert (
        result["status"]
        == {"offline": "Offline", "timeout": "Timeout", "disconnect": "Disconnected"}[
            scenario
        ]
    )
    assert (
        await db_session.scalar(select(func.count()).select_from(ChargingSession)) == 0
    )


async def test_accepted_requires_actual_start_and_deadline_allows_retry(
    db_session, fixture
):
    _, _, connector, driver, _, conn, _ = fixture
    reply_with(conn)
    key = uuid4()
    await remote_start(driver.id, key, connector.id)
    await expire_start_requests(db_session, datetime.now(UTC) + timedelta(seconds=61))
    await db_session.commit()
    assert (await remote_start(driver.id, key, connector.id))[
        "status"
    ] == "StartNotConfirmed"
    assert (await remote_start(driver.id, uuid4(), connector.id))[
        "status"
    ] == "Accepted"


async def test_real_transaction_ownership_meter_updates_and_other_driver_forbidden(
    db_session, fixture
):
    _, _, connector, driver, _, conn, _ = fixture
    reply_with(conn)
    key = uuid4()
    await remote_start(driver.id, key, connector.id)
    raw = decode_frame(conn.websocket.send_text.call_args.args[0]).payload["idTag"]
    stamp = datetime.now(UTC) - timedelta(seconds=10)
    response = await start(db_session, conn, raw, stamp)
    tid = response.payload["transactionId"]
    assert response.payload["idTagInfo"]["status"] == "Accepted"
    await db_session.commit()
    assert (await remote_start(driver.id, key, connector.id))["status"] == "Started"
    app.dependency_overrides[get_current_actor] = lambda: CurrentActor(
        driver.id, frozenset({"driver"})
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        current = (await client.get("/api/v1/driver/charging/current")).json()
        assert current["session"]["id"] == tid
        assert Decimal(current["session"]["energy_kwh"]) == 0
        await call(
            db_session, conn, "MeterValues", meter_payload(tid, datetime.now(UTC), 2500)
        )
        await db_session.commit()
        current = (await client.get("/api/v1/driver/charging/current")).json()
        assert Decimal(current["session"]["energy_kwh"]) == Decimal("1.5")
        assert current["session"]["latest_meter_at"]
        assert current["session"]["elapsed_seconds"] >= 10
        assert "driver_id" not in current["session"]
        app.dependency_overrides[get_current_actor] = lambda: CurrentActor(
            uuid4(), frozenset({"driver"})
        )
        assert (
            await client.get(f"/api/v1/driver/charging/sessions/{tid}")
        ).status_code == 403
        assert (await client.get("/api/v1/driver/charging/current")).json()[
            "session"
        ] is None


async def test_driver_endpoint_roles_body_and_empty_state(db_session, fixture):
    station, _, connector, driver, _, conn, _ = fixture
    app.dependency_overrides[get_current_actor] = lambda: CurrentActor(
        driver.id, frozenset({"driver"})
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        assert (await client.get("/api/v1/driver/charging/current")).json() == {
            "session": None,
            "start_request": None,
        }
        assert (
            await client.get(f"/api/v1/driver/stations/{station.id}/connectors")
        ).json()["items"][0]["id"] == str(connector.id)
        assert (
            await client.post(
                "/api/v1/driver/charging/start",
                json={
                    "request_id": str(uuid4()),
                    "connector_id": str(connector.id),
                    "id_tag": "FORGED",
                },
            )
        ).status_code == 422
        app.dependency_overrides[get_current_actor] = lambda: CurrentActor(
            driver.id, frozenset({"operator"})
        )
        assert (await client.get("/api/v1/driver/charging/current")).status_code == 403
        assert (
            await client.post(
                "/api/v1/driver/charging/start",
                json={"request_id": str(uuid4()), "connector_id": str(connector.id)},
            )
        ).status_code == 403
        conn.websocket.send_text.assert_not_awaited()


async def test_pending_scan_releases_request_without_resend(db_session, fixture):
    _, charger, connector, driver, _, conn, _ = fixture
    key = uuid4()
    now = datetime.now(UTC)
    db_session.add(
        ControlRequest(
            id=key,
            actor_id=driver.id,
            actor_email=driver.email,
            charge_point_id=charger.id,
            charge_point_code=charger.code,
            action="RemoteStartTransaction",
            payload={"connectorId": 1},
            created_at=now,
        )
    )
    db_session.add(
        DriverStartRequest(
            id=key,
            driver_id=driver.id,
            connector_id=connector.id,
            charge_point_id=charger.id,
            created_at=now,
            status="Pending",
            reply_status="Pending",
            lease_until=now,
        )
    )
    await db_session.flush()
    assert await expire_start_requests(db_session) == 1
    await db_session.commit()
    assert (await remote_start(driver.id, key, connector.id))["status"] == "Timeout"
    conn.websocket.send_text.assert_not_awaited()


@pytest.mark.parametrize("state", ["blocked", "expired"])
async def test_virtual_card_uses_same_authorization_controls(
    db_session, fixture, state
):
    _, _, connector, driver, _, conn, _ = fixture
    await virtual_tag(db_session, driver)
    tag = await db_session.get(DriverVirtualTag, driver.id)
    card = await db_session.get(ChargingCard, tag.card_id)
    if state == "blocked":
        card.status = "blocked"
    else:
        card.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await db_session.commit()
    with pytest.raises(HTTPException) as error:
        await remote_start(driver.id, uuid4(), connector.id)
    assert error.value.status_code == 409
    conn.websocket.send_text.assert_not_awaited()


async def test_idempotency_key_cannot_be_rebound(db_session, fixture):
    _, _, connector, driver, _, conn, _ = fixture
    reply_with(conn, "Rejected")
    key = uuid4()
    await remote_start(driver.id, key, connector.id)
    with pytest.raises(HTTPException) as error:
        await remote_start(uuid4(), key, connector.id)
    assert error.value.status_code == 409
    assert conn.websocket.send_text.await_count == 1
