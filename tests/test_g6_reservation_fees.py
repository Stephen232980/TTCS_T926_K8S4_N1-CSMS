"""S-50 financial decisions with real PostgreSQL and the G5 command worker."""
# ruff: noqa: F811 -- pytest fixtures imported from the integration fleet

import asyncio
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from src.entrypoints.http import app
from src.modules.charging.driver import remote_start
from src.modules.charging.driver_models import DriverVirtualTag
from src.modules.identity.authorization import CurrentActor
from src.modules.identity.dependencies import get_current_actor
from src.modules.reservations import fees, worker
from src.modules.reservations.models import (
    Reservation,
    ReservationCapability,
    ReservationPolicy,
)
from src.modules.reservations.service import create_reservation
from src.modules.stations.models import ChargePoint, Station
from src.modules.wallet.models import Wallet, WalletLedger
from tests.test_charging_sessions import call
from tests.test_g5_reservations import (  # noqa: F401
    EVIDENCE,
    api_db,
    committed_tariff_db,
    fleet,
    reply,
    request,
    reservation_fleet,
)


@pytest.fixture
async def paid(reservation_fleet, monkeypatch):
    factory, _, point, connector, driver, *_ = reservation_fleet
    monkeypatch.setattr(fees, "SessionFactory", factory)
    async with factory() as db, db.begin():
        db.add(ReservationPolicy(station_id=point.station_id, fee_vnd=10000, version=1))
    async with factory() as db, db.begin():
        row = await create_reservation(
            db, driver.id, uuid4(), connector.id, None, EVIDENCE, 10000, 1
        )
    reply(reservation_fleet[6])
    await worker.cycle()
    return reservation_fleet, row


async def expire(fixture, identifier):
    factory, _, point, *_ = fixture
    now = datetime.now(UTC)
    async with factory() as db, db.begin():
        row = await db.get(Reservation, identifier)
        row.created_at = row.arrival_at = now - timedelta(minutes=20)
        row.expires_at = now - timedelta(seconds=40)
        row.activated_at = now - timedelta(minutes=19)
        cp = await db.get(ChargePoint, point.id)
        cp.last_boot_at, cp.last_seen_at = now - timedelta(hours=1), now
        (await db.get(ReservationCapability, point.id)).boot_at = cp.last_boot_at


async def test_five_scans_two_workers_one_fee_snapshot_negative_wallet(paid):
    fixture, row = paid
    factory, _, point, _, driver, _, conn, _ = fixture
    await expire(fixture, row.id)
    async with factory() as db, db.begin():
        (await db.get(ReservationPolicy, point.station_id)).fee_vnd = 50000
        (
            await db.scalar(select(Wallet).where(Wallet.driver_id == driver.id))
        ).balance_vnd = 1
    await worker.reconcile(row.id)
    await asyncio.gather(fees.fee_one(row.id), fees.fee_one(row.id))
    for _ in range(5):
        await fees.fee_cycle()
    reply(conn, "Rejected")
    await worker.cycle()
    async with factory() as db:
        stored = await db.get(Reservation, row.id)
        ledger = await db.scalar(select(WalletLedger))
        wallet = await db.scalar(select(Wallet).where(Wallet.driver_id == driver.id))
        assert stored.fee_decision == "charged" and stored.fee_vnd == 10000
        assert stored.status == "expiry_release_pending"
        assert ledger.entry_type == "reservation_fee" and ledger.amount_vnd == -10000
        assert ledger.reference_id == str(row.id) and stored.fee_ledger_id == ledger.id
        assert wallet.balance_vnd == -9999
        assert await db.scalar(select(func.count()).select_from(WalletLedger)) == 1
    with pytest.raises(HTTPException):
        await remote_start(driver.id, uuid4(), fixture[3].id)
    from src.modules.reservations.models import ReservationCommand

    reply(conn, "Accepted")
    async with factory() as db, db.begin():
        command = await db.scalar(
            select(ReservationCommand).where(
                ReservationCommand.reservation_id == row.id,
                ReservationCommand.action == "CancelReservation",
            )
        )
        command.next_attempt_at = datetime.now(UTC)
    await worker.cycle()
    with pytest.raises(HTTPException) as denied:
        await remote_start(driver.id, uuid4(), fixture[3].id)
    assert denied.value.detail["reason"] == "wallet_low"


@pytest.mark.parametrize(
    "fault",
    ["offline", "uncertain", "suspended", "cancelled", "no_contact_after_expiry"],
)
async def test_no_penalty_without_reliable_hold_or_after_timely_cancel(paid, fault):
    fixture, row = paid
    factory, station, point, *_ = fixture
    if fault == "cancelled":
        assert (
            await request("POST", f"/{row.id}/cancel", {"request_id": str(uuid4())})
        ).status_code == 202
    await expire(fixture, row.id)
    async with factory() as db, db.begin():
        if fault == "offline":
            (await db.get(ChargePoint, point.id)).status = "offline"
        if fault == "uncertain":
            stored = await db.get(Reservation, row.id)
            stored.status, stored.activated_at = "uncertain", None
        if fault == "suspended":
            (await db.get(Station, station.id)).status = "suspended"
        if fault == "cancelled":
            (await db.get(Reservation, row.id)).cancel_requested_at = datetime.now(
                UTC
            ) - timedelta(minutes=1)
        if fault == "no_contact_after_expiry":
            stored = await db.get(Reservation, row.id)
            (await db.get(ChargePoint, point.id)).last_seen_at = (
                stored.expires_at - timedelta(seconds=1)
            )
    await worker.reconcile(row.id)
    await fees.fee_one(row.id)
    async with factory() as db:
        stored = await db.get(Reservation, row.id)
        assert stored.fee_decision in {"waived", "review"}
        assert await db.scalar(select(func.count()).select_from(WalletLedger)) == 0


async def test_fee_audit_failure_rolls_back_and_retry_is_atomic(paid, monkeypatch):
    fixture, row = paid
    factory, *_ = fixture
    await expire(fixture, row.id)
    await worker.reconcile(row.id)
    real_audit = fees.ghi_nhat_ky
    monkeypatch.setattr(
        fees, "ghi_nhat_ky", AsyncMock(side_effect=RuntimeError("audit offline"))
    )
    with pytest.raises(RuntimeError):
        await fees.fee_one(row.id)
    async with factory() as db:
        assert (await db.get(Reservation, row.id)).fee_decision == "pending"
        assert await db.scalar(select(func.count()).select_from(WalletLedger)) == 0
    monkeypatch.setattr(fees, "ghi_nhat_ky", real_audit)
    await fees.fee_one(row.id)
    async with factory() as db:
        assert (await db.get(Reservation, row.id)).fee_decision == "charged"
        assert await db.scalar(select(func.count()).select_from(WalletLedger)) == 1


async def test_late_start_marks_review_without_refunding_or_second_debit(paid):
    fixture, row = paid
    factory, _, _, _, driver, _, conn, _ = fixture
    await expire(fixture, row.id)
    await worker.reconcile(row.id)
    await fees.fee_one(row.id)
    async with factory() as db, db.begin():
        stored = await db.get(Reservation, row.id)
        tag = (await db.get(DriverVirtualTag, driver.id)).id_tag
        result = await call(
            db,
            conn,
            "StartTransaction",
            {
                "connectorId": 1,
                "reservationId": row.ocpp_id,
                "idTag": tag,
                "meterStart": 1000,
                "timestamp": (stored.expires_at - timedelta(seconds=1)).isoformat(),
            },
        )
        assert result.payload["transactionId"] == 0
        assert stored.fee_decision == "review" and stored.fee_ledger_id is not None
    async with factory() as db:
        assert await db.scalar(select(func.count()).select_from(WalletLedger)) == 1


async def test_fee_quote_acceptance_and_wallet_threshold(reservation_fleet):
    factory, _, point, connector, driver, *_ = reservation_fleet
    async with factory() as db, db.begin():
        db.add(ReservationPolicy(station_id=point.station_id, fee_vnd=10000, version=1))
        (
            await db.scalar(select(Wallet).where(Wallet.driver_id == driver.id))
        ).balance_vnd = 20000
    body = {"connector_id": str(connector.id), "request_id": str(uuid4())}
    assert (await request("POST", body=body)).json()[
        "detail"
    ] == "reservation_policy_changed"
    assert (
        await request(
            "POST",
            body={**body, "accepted_fee_vnd": 9000, "accepted_policy_version": 1},
        )
    ).status_code == 409
    response = await request(
        "POST", body={**body, "accepted_fee_vnd": 10000, "accepted_policy_version": 1}
    )
    assert (
        response.status_code == 409
        and response.json()["detail"]["reason"] == "wallet_low"
    )
    async with factory() as db, db.begin():
        (
            await db.scalar(select(Wallet).where(Wallet.driver_id == driver.id))
        ).balance_vnd = 30000
    response = await request(
        "POST", body={**body, "accepted_fee_vnd": 10000, "accepted_policy_version": 1}
    )
    assert response.status_code == 202 and response.json()["no_show_fee_vnd"] == "10000"


async def test_policy_owner_scope_stale_version_and_strict_validation(
    reservation_fleet,
):
    _, station, _, connector, driver, other, *_ = reservation_fleet
    path = f"/api/v1/owner/stations/{station.id}/reservation-policy"
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as http:
        assert (await http.get(path)).status_code == 403
        app.dependency_overrides[get_current_actor] = lambda: CurrentActor(
            other.id, frozenset({"station_owner"})
        )
        assert (
            await http.put(path, json={"fee_vnd": 10000, "expected_version": 0})
        ).status_code == 403
        app.dependency_overrides[get_current_actor] = lambda: CurrentActor(
            station.owner_id, frozenset({"station_owner"})
        )
        assert (await http.get(path)).json() == {"fee_vnd": 0, "version": 0}
        for amount in (-1, 1000001, True, 1.5):
            assert (
                await http.put(path, json={"fee_vnd": amount, "expected_version": 0})
            ).status_code == 422
        assert (
            await http.put(path, json={"fee_vnd": 10000, "expected_version": 0})
        ).json() == {"fee_vnd": 10000, "version": 1}
        assert (
            await http.put(path, json={"fee_vnd": 20000, "expected_version": 0})
        ).status_code == 409
        app.dependency_overrides[get_current_actor] = lambda: CurrentActor(
            driver.id, frozenset({"driver"})
        )
        assert (
            await request("GET", f"/policy?connector_id={connector.id}")
        ).json() == {"fee_vnd": 10000, "version": 1}


async def test_zero_fee_skips_ledger_and_legacy_roundtrip_is_exempt(
    reservation_fleet, monkeypatch
):
    from tests.test_g5_reservations import book

    factory, *_ = reservation_fleet
    monkeypatch.setattr(fees, "SessionFactory", factory)
    row = await book(reservation_fleet)
    reply(reservation_fleet[6])
    await worker.cycle()
    url = factory.kw["bind"].url.render_as_string(hide_password=False)
    for args in (["downgrade", "d240024a2026"], ["upgrade", "head"]):
        result = await asyncio.to_thread(
            subprocess.run,
            [sys.executable, "-m", "alembic", *args],
            env=os.environ | {"DATABASE_URL": url},
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
    async with factory() as db:
        stored = await db.get(Reservation, row.id)
        assert stored.fee_decision == "legacy_exempt" and stored.fee_vnd == 0
    await expire(reservation_fleet, row.id)
    await fees.fee_one(row.id)
    async with factory() as db:
        assert await db.scalar(select(func.count()).select_from(WalletLedger)) == 0


async def test_financial_downgrade_refuses_to_delete_posted_fee(paid):
    fixture, row = paid
    factory, *_ = fixture
    await expire(fixture, row.id)
    await worker.reconcile(row.id)
    await fees.fee_one(row.id)
    url = factory.kw["bind"].url.render_as_string(hide_password=False)
    result = await asyncio.to_thread(
        subprocess.run,
        [sys.executable, "-m", "alembic", "downgrade", "d240024a2026"],
        env=os.environ | {"DATABASE_URL": url},
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0 and "financial downgrade" in result.stderr
    async with factory() as db:
        assert (await db.get(Reservation, row.id)).fee_decision == "charged"
        assert await db.scalar(select(func.count()).select_from(WalletLedger)) == 1


async def test_zero_fee_new_booking_does_not_create_money_entry(
    reservation_fleet, monkeypatch
):
    from tests.test_g5_reservations import book

    factory, *_ = reservation_fleet
    monkeypatch.setattr(fees, "SessionFactory", factory)
    row = await book(reservation_fleet)
    reply(reservation_fleet[6])
    await worker.cycle()
    await expire(reservation_fleet, row.id)
    await worker.reconcile(row.id)
    await fees.fee_one(row.id)
    async with factory() as db:
        stored = await db.get(Reservation, row.id)
        assert stored.fee_decision == "waived" and stored.fee_reason == "zero_fee"
        assert await db.scalar(select(func.count()).select_from(WalletLedger)) == 0


async def test_start_source_before_expiry_arrives_within_grace_after_cancel_ack(paid):
    fixture, row = paid
    factory, _, _, _, driver, _, conn, _ = fixture
    await expire(fixture, row.id)
    async with factory() as db, db.begin():
        (await db.get(Reservation, row.id)).expires_at = datetime.now(UTC) - timedelta(
            seconds=15
        )
    await worker.cycle()
    async with factory() as db:
        assert (await db.get(Reservation, row.id)).status == "expired"
    await fees.fee_one(row.id)
    async with factory() as db, db.begin():
        stored = await db.get(Reservation, row.id)
        tag = (await db.get(DriverVirtualTag, driver.id)).id_tag
        result = await call(
            db,
            conn,
            "StartTransaction",
            {
                "connectorId": 1,
                "reservationId": row.ocpp_id,
                "idTag": tag,
                "meterStart": 1000,
                "timestamp": (stored.expires_at - timedelta(seconds=1)).isoformat(),
            },
        )
        assert result.payload["transactionId"] > 0
        assert stored.status == "consumed" and stored.fee_decision == "waived"
    async with factory() as db:
        assert await db.scalar(select(func.count()).select_from(WalletLedger)) == 0
