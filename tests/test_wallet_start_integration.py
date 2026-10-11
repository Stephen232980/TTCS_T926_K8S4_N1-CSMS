"""Real wallet/tariff checks at API and OCPP boundaries, including reply races."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, func, select

from src.modules.charging.driver import expire_start_requests, remote_start
from src.modules.charging.driver_models import DriverStartRequest
from src.modules.charging.driver_router import current_snapshot
from src.modules.charging.models import ChargingSession
from src.modules.ocpp.control_models import ControlRequest
from src.modules.ocpp.frames import Frame, decode_frame, encode_frame
from src.modules.ocpp.transport import handle_message
from src.modules.pricing.models import Tariff, TariffBand
from src.modules.wallet.models import Wallet
from tests.test_charging_sessions import call, start
from tests.test_driver_charging import db_session as driver_database
from tests.test_driver_charging import fixture as driver_fixture
from tests.test_ocpp_control import reply_with
from tests.test_wallet_eligibility import add_tariff

db_session = driver_database
fixture = driver_fixture


async def wallet_case(session, data, balance):
    station, _, _, driver, _, _, _ = data
    await add_tariff(
        session, station.id, datetime.now(UTC).date() - timedelta(days=1), (2500,)
    )
    wallet = await session.scalar(select(Wallet).where(Wallet.driver_id == driver.id))
    wallet.balance_vnd = balance
    await session.commit()
    return wallet


@pytest.mark.parametrize("balance", [12499, 12500])
async def test_real_wallet_authorize_and_start_boundaries(db_session, fixture, balance):
    _, _, _, _, _, conn, tag = fixture
    await wallet_case(db_session, fixture, balance)
    expected = "Accepted" if balance == 12500 else "Blocked"
    authorized = await call(db_session, conn, "Authorize", {"idTag": tag})
    assert authorized.payload["idTagInfo"]["status"] == expected
    begun = await start(db_session, conn, tag)
    assert begun.payload["idTagInfo"]["status"] == expected
    assert await db_session.scalar(
        select(func.count()).select_from(ChargingSession)
    ) == int(balance == 12500)


@pytest.mark.parametrize("balance", [12499, 12500])
async def test_real_wallet_api_boundaries(db_session, fixture, balance):
    _, _, connector, driver, _, conn, _ = fixture
    await wallet_case(db_session, fixture, balance)
    key = uuid4()
    reply_with(conn)
    if balance == 12499:
        with pytest.raises(HTTPException) as denied:
            await remote_start(driver.id, key, connector.id)
        assert denied.value.status_code == 409
        assert denied.value.detail == "wallet_low"
        assert await db_session.get(DriverStartRequest, key) is None
        assert await db_session.get(ControlRequest, key) is None
        conn.websocket.send_text.assert_not_awaited()
    else:
        assert (await remote_start(driver.id, key, connector.id))[
            "status"
        ] == "Accepted"
        conn.websocket.send_text.assert_awaited_once()


@pytest.mark.parametrize("before_reply", [False, True])
@pytest.mark.parametrize(
    "reason", ["wallet_low", "wallet_locked", "wallet_missing", "tariff_unavailable"]
)
async def test_wallet_changes_reject_durable_request_without_session(
    db_session, fixture, before_reply, reason
):
    _, _, connector, driver, _, conn, _ = fixture
    wallet = await wallet_case(db_session, fixture, 12500)
    driver_id = driver.id
    key = uuid4()

    async def deny_start(raw):
        command = decode_frame(raw)
        if reason == "tariff_unavailable":
            await db_session.execute(
                delete(TariffBand).where(
                    TariffBand.tariff_id.in_(
                        select(Tariff.id).where(Tariff.station_id == fixture[0].id)
                    )
                )
            )
        elif reason == "wallet_missing":
            await db_session.delete(wallet)
        elif reason == "wallet_locked":
            wallet.status = "locked"
        else:
            wallet.balance_vnd = 12499
        await db_session.commit()
        reply = await start(db_session, conn, command.payload["idTag"])
        assert reply.payload == {"transactionId": 0, "idTagInfo": {"status": "Blocked"}}
        await db_session.commit()

    if before_reply:

        async def answer(raw):
            await deny_start(raw)
            command = decode_frame(raw)
            await handle_message(
                conn, encode_frame(Frame(3, command.message_id, {"status": "Accepted"}))
            )

        conn.websocket.send_text = AsyncMock(side_effect=answer)
        result = await remote_start(driver.id, key, connector.id)
    else:
        reply_with(conn)
        assert (await remote_start(driver.id, key, connector.id))[
            "status"
        ] == "Accepted"
        await deny_start(conn.websocket.send_text.call_args.args[0])
        result = await remote_start(driver.id, key, connector.id)

    assert result["status"] == "Rejected"
    assert result["reply_status"] == "Accepted"
    assert result["rejection_reason"] == reason
    assert result["deadline"] is None
    assert result["session_id"] is None
    await expire_start_requests(db_session, datetime.now(UTC) + timedelta(seconds=61))
    await db_session.commit()
    db_session.expire_all()
    snapshot = await current_snapshot(db_session, driver_id)
    assert snapshot["session"] is None
    assert snapshot["start_request"]["status"] == "Rejected"
    assert snapshot["start_request"]["rejection_reason"] == reason
    assert (
        await db_session.scalar(select(func.count()).select_from(ChargingSession)) == 0
    )
    conn.websocket.send_text.assert_awaited_once()


async def test_physical_card_denial_does_not_reject_virtual_request(
    db_session, fixture
):
    _, _, connector, driver, _, conn, physical_tag = fixture
    wallet = await wallet_case(db_session, fixture, 12500)
    key = uuid4()
    reply_with(conn)
    await remote_start(driver.id, key, connector.id)
    wallet.balance_vnd = 12499
    await db_session.commit()
    assert (await start(db_session, conn, physical_tag)).payload["idTagInfo"][
        "status"
    ] == "Blocked"
    await db_session.commit()
    result = await remote_start(driver.id, key, connector.id)
    assert result["status"] == "Accepted"
    assert result["rejection_reason"] is None


async def test_rejected_request_releases_lease_and_keeps_replay_after_topup(
    db_session, fixture
):
    _, _, connector, driver, _, conn, _ = fixture
    wallet = await wallet_case(db_session, fixture, 12500)
    key = uuid4()
    reply_with(conn)
    await remote_start(driver.id, key, connector.id)
    virtual = decode_frame(conn.websocket.send_text.call_args.args[0]).payload["idTag"]
    wallet.balance_vnd = 12499
    await db_session.commit()
    await start(db_session, conn, virtual)
    await db_session.commit()
    wallet.balance_vnd = 12500
    await db_session.commit()
    old = await remote_start(driver.id, key, connector.id)
    assert old["status"] == "Rejected" and old["rejection_reason"] == "wallet_low"
    conn.websocket.send_text.assert_awaited_once()
    fresh = await remote_start(driver.id, uuid4(), connector.id)
    assert fresh["status"] == "Accepted" and fresh["rejection_reason"] is None
    assert conn.websocket.send_text.await_count == 2
