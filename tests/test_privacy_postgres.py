"""Committed database regression probes; never point these at a shared database."""

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from src.modules.charging.models import (
    ChargingCard,
    ChargingSession,
    PendingChargingMessage,
)
from src.modules.identity.authorization import AuthorizationEvidence
from src.modules.identity.models import User
from src.modules.identity.security import hash_password
from src.modules.privacy.models import PrivacyRequest
from src.modules.privacy.schemas import PrivacyDecision
from src.modules.privacy.service import PrivacyRetentionService
from src.modules.reservations.models import Reservation
from src.modules.stations.models import ChargePoint, Connector, Station
from src.modules.wallet.models import Wallet, WalletLedger
from src.platform.database.session import SessionFactory

AUTH = AuthorizationEvidence(permission="admin.privacy.manage", roles=("admin",))


async def seed(balance: int = 0):
    uid, admin = uuid4(), uuid4()
    password_hash = hash_password("privacy-test-password")
    async with SessionFactory() as db:
        db.add_all(
            [
                User(id=uid, email=f"{uid}@test.local", password_hash=password_hash),
                User(
                    id=admin, email=f"{admin}@test.local", password_hash=password_hash
                ),
            ]
        )
        await db.flush()
        wallet = Wallet(driver_id=uid, balance_vnd=balance)
        db.add(wallet)
        db.add(
            ChargingCard(
                driver_id=uid,
                issuer_id=admin,
                tag_hash=uuid4().hex * 2,
                tag_tail="1234",
            )
        )
        await db.flush()
        if balance:
            db.add(
                WalletLedger(
                    wallet_id=wallet.id,
                    entry_type="gateway_topup",
                    amount_vnd=balance,
                    balance_after_vnd=balance,
                    reference_type="test",
                    reference_id=str(uuid4()),
                )
            )
        await db.commit()
    return uid, admin


@pytest.mark.parametrize(
    "balance,blocker",
    [(1000000, "refund_required"), (-5000, "debt_resolution_required"), (0, None)],
)
async def test_request_approval_and_legacy_execution_preserve_committed_data(
    balance, blocker
):
    uid, admin = await seed(balance)
    async with SessionFactory() as db:
        receipt = await PrivacyRetentionService(db).create_request(
            uid, "privacy-test-password", "User request"
        )
        assert receipt.status == "pending"
        if blocker:
            assert blocker in receipt.blockers
        else:
            assert "refund_required" not in receipt.blockers
            assert "debt_resolution_required" not in receipt.blockers
        approved = await PrivacyRetentionService(db).review_request(
            receipt.id,
            PrivacyDecision(
                decision="approved",
                reason="Reviewed intake only",
                policy_version="CSMS-PRIVACY-2026-01",
            ),
            admin,
            AUTH,
        )
        assert approved.status == "approved"
        assert approved.execution_status == "queued"
        with pytest.raises(HTTPException, match="privacy_execution_unavailable"):
            await PrivacyRetentionService(db).anonymize_user(
                uid, admin, "User request", "CONFIRM_ANONYMIZE"
            )
    # New session observes committed state rather than ORM identity-map cache.
    async with SessionFactory() as db:
        user = await db.get(User, uid)
        assert user.status == "active"
        assert user.email == f"{uid}@test.local"
        assert (
            await db.scalar(select(Wallet).where(Wallet.driver_id == uid))
        ).balance_vnd == balance
        total = await db.scalar(
            select(func.sum(WalletLedger.amount_vnd))
            .join(Wallet)
            .where(Wallet.driver_id == uid)
        )
        assert (total or 0) == balance
        assert (
            await db.scalar(select(ChargingCard).where(ChargingCard.driver_id == uid))
        ).status == "active"
        request = await db.get(PrivacyRequest, receipt.id)
        assert request.policy_version == "CSMS-PRIVACY-2026-01"
        assert request.reviewer_id == admin


async def test_concurrent_intake_is_single_active_request_and_survives_new_session():
    uid, _ = await seed()

    async def submit():
        async with SessionFactory() as db:
            return await PrivacyRetentionService(db).create_request(
                uid, "privacy-test-password", "User request"
            )

    first, second = await asyncio.gather(submit(), submit())
    assert first.id == second.id
    async with SessionFactory() as db:
        assert (
            await db.scalar(
                select(func.count())
                .select_from(PrivacyRequest)
                .where(PrivacyRequest.user_id == uid)
            )
            == 1
        )
        assert [r.id for r in await PrivacyRetentionService(db).list_requests(uid)] == [
            first.id
        ]
        assert await PrivacyRetentionService(db).list_requests(uuid4()) == []


async def test_failed_reauthentication_creates_nothing():
    uid, _ = await seed()
    async with SessionFactory() as db:
        with pytest.raises(HTTPException) as error:
            await PrivacyRetentionService(db).create_request(uid, "wrong", "Request")
        assert error.value.status_code == 403
        await db.rollback()
    async with SessionFactory() as db:
        assert (
            await db.scalar(
                select(func.count())
                .select_from(PrivacyRequest)
                .where(PrivacyRequest.user_id == uid)
            )
            == 0
        )


async def test_audit_failure_rolls_back_receipt_and_allows_retry():
    uid, _ = await seed()
    async with SessionFactory() as db:
        with (
            patch(
                "src.modules.privacy.service.ghi_nhat_ky",
                side_effect=RuntimeError("injected audit failure"),
            ),
            pytest.raises(RuntimeError),
        ):
            await PrivacyRetentionService(db).create_request(
                uid, "privacy-test-password", "Request"
            )
        await db.rollback()
    async with SessionFactory() as db:
        assert (
            await db.scalar(
                select(func.count())
                .select_from(PrivacyRequest)
                .where(PrivacyRequest.user_id == uid)
            )
            == 0
        )
        receipt = await PrivacyRetentionService(db).create_request(
            uid, "privacy-test-password", "Retry request"
        )
        assert receipt.status == "pending"


async def test_rejection_is_durable_and_cannot_be_reapproved():
    uid, admin = await seed()
    async with SessionFactory() as db:
        service = PrivacyRetentionService(db)
        receipt = await service.create_request(uid, "privacy-test-password", "Request")
        decision = PrivacyDecision(
            decision="rejected",
            reason="Needs clarification",
            policy_version="CSMS-PRIVACY-2026-01",
        )
        await service.review_request(receipt.id, decision, admin, AUTH)
        with pytest.raises(HTTPException) as error:
            await service.review_request(receipt.id, decision, admin, AUTH)
        assert error.value.status_code == 409
        await db.rollback()
    async with SessionFactory() as db:
        assert (await db.get(PrivacyRequest, receipt.id)).status == "rejected"
        new = await PrivacyRetentionService(db).create_request(
            uid, "privacy-test-password", "New request"
        )
        assert new.id != receipt.id


async def test_hold_after_approval_is_visible_and_cleanup_deletes_nothing():
    uid, admin = await seed()
    async with SessionFactory() as db:
        service = PrivacyRetentionService(db)
        receipt = await service.create_request(uid, "privacy-test-password", "Request")
        await service.review_request(
            receipt.id,
            PrivacyDecision(
                decision="approved",
                reason="Review only",
                policy_version="CSMS-PRIVACY-2026-01",
            ),
            admin,
            AUTH,
        )
        await service.set_legal_hold(uid, True, "Open dispute", admin, AUTH)
    async with SessionFactory() as db:
        service = PrivacyRetentionService(db)
        assert (
            "legal_hold_or_unsettled_charging"
            in (await service.list_requests(uid))[0].blockers
        )
        assert (await service.run_retention_cleanup(admin)).total_deleted == 0
        assert (await db.get(User, uid)).status == "active"


@pytest.mark.parametrize(
    "kind,expected",
    [
        ("cable", "connector_release_required"),
        ("settlement", "legal_hold_or_unsettled_charging"),
        ("booking", "reservation_or_fee_pending"),
        ("fee", "reservation_or_fee_pending"),
    ],
)
async def test_committed_activity_blockers_and_old_pending_evidence(kind, expected):
    uid, admin = await seed()
    now = datetime.now(UTC)
    pending_id = uuid4()
    async with SessionFactory() as db:
        station = Station(
            owner_id=admin,
            name="Privacy test",
            address="Test",
            latitude=Decimal(0),
            longitude=Decimal(0),
        )
        db.add(station)
        await db.flush()
        cp = ChargePoint(station_id=station.id, code=f"privacy-{uuid4().hex}")
        db.add(cp)
        await db.flush()
        connector = Connector(charge_point_id=cp.id, connector_number=1)
        db.add(connector)
        await db.flush()
        db.add(
            PendingChargingMessage(
                id=pending_id,
                charge_point_id=cp.id,
                action="MeterValues",
                message_id=str(uuid4()),
                reason="transaction_missing",
                payload={},
                received_at=now - timedelta(days=30),
            )
        )
        if kind in {"cable", "settlement"}:
            db.add(
                ChargingSession(
                    charge_point_id=cp.id,
                    connector_id=connector.id,
                    driver_id=uid,
                    tag_tail="1234",
                    authorization_status="Accepted",
                    started_at=now - timedelta(hours=1),
                    ended_at=now,
                    meter_start_wh=Decimal(0),
                    meter_stop_wh=Decimal(1000),
                    energy_kwh=Decimal(1),
                    connector_released_at=None if kind == "cable" else now,
                    settlement_completed_at=now if kind == "cable" else None,
                    settlement_reason="zero_invoice" if kind == "cable" else None,
                )
            )
        else:
            card = await db.scalar(
                select(ChargingCard).where(ChargingCard.driver_id == uid)
            )
            db.add(
                Reservation(
                    id=uuid4(),
                    driver_id=uid,
                    station_id=station.id,
                    charge_point_id=cp.id,
                    connector_id=connector.id,
                    card_id=card.id,
                    request_hash="a" * 64,
                    status="active" if kind == "booking" else "cancelled",
                    fee_decision="waived" if kind == "booking" else "review",
                    created_at=now,
                    updated_at=now,
                    arrival_at=now + timedelta(minutes=1),
                    expires_at=now + timedelta(minutes=10),
                )
            )
        await db.commit()
    async with SessionFactory() as db:
        service = PrivacyRetentionService(db)
        receipt = await service.create_request(uid, "privacy-test-password", "Request")
        assert expected in receipt.blockers
        assert (await service.run_retention_cleanup(admin)).total_deleted == 0
    async with SessionFactory() as db:
        assert await db.get(PendingChargingMessage, pending_id) is not None
