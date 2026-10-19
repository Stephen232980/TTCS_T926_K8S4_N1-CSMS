import asyncio
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from src.modules.identity.models import Role, UserRole
from src.modules.privacy.executor import execute_job, executor_engine
from src.modules.privacy.models import PrivacyJob
from src.modules.privacy.schemas import PrivacyDecision
from src.modules.privacy.service import PrivacyRetentionService
from src.modules.wallet.models import Wallet, WalletLedger
from src.platform.database.session import SessionFactory
from tests.test_privacy_postgres import AUTH, seed


async def approved(balance=495):
    uid, admin = await seed(balance)
    async with SessionFactory() as db:
        role = await db.scalar(select(Role).where(Role.code == "admin"))
        db.add(UserRole(user_id=admin, role_id=role.id))
        await db.commit()
        service = PrivacyRetentionService(db)
        receipt = await service.create_request(
            uid, "privacy-test-password", "Privacy refund test"
        )
        await service.review_request(
            receipt.id,
            PrivacyDecision(
                decision="approved",
                reason="Reviewed test",
                policy_version="CSMS-PRIVACY-2026-01",
            ),
            admin,
            AUTH,
        )
        job = await db.scalar(
            select(PrivacyJob).where(PrivacyJob.request_id == receipt.id)
        )
        job.status = "needs_review"
        job.last_error = "wallet_refund_or_debt_required"
        await db.commit()
        return uid, admin, receipt.id, job.id


async def retry(admin, request_id, confirmed=True, expected=495):
    async with SessionFactory() as db:
        return await PrivacyRetentionService(db).enqueue_execution(
            request_id,
            admin,
            AUTH,
            "Confirmed external manual refund",
            external_refund_confirmed=confirmed,
            expected_balance_vnd=expected,
        )


@pytest.mark.asyncio
async def test_external_confirmation_commits_one_debit_and_worker_completes():
    uid, admin, rid, jid = await approved()
    first, second = await asyncio.gather(retry(admin, rid), retry(admin, rid))
    assert first.execution_status == second.execution_status == "queued"
    async with SessionFactory() as db:
        wallet = await db.scalar(select(Wallet).where(Wallet.driver_id == uid))
        wallet_id = wallet.id
        assert wallet.balance_vnd == 0
        entries = (
            await db.scalars(
                select(WalletLedger).where(
                    WalletLedger.wallet_id == wallet_id,
                    WalletLedger.entry_type == "adjustment",
                )
            )
        ).all()
        assert len(entries) == 1
        assert entries[0].amount_vnd == -495 and entries[0].actor_id == admin
        assert (
            await db.scalar(
                select(func.sum(WalletLedger.amount_vnd)).where(
                    WalletLedger.wallet_id == wallet_id
                )
            )
            == 0
        )
    engine = executor_engine()
    try:
        async with asyncio.timeout(10):
            checkpoint, replay = await asyncio.gather(
                execute_job(engine, jid), retry(admin, rid)
            )
        assert checkpoint == 3
        assert replay.execution_status in {"queued", "processing", "completed"}
    finally:
        await engine.dispose()
    assert (await retry(admin, rid)).execution_status == "completed"
    async with SessionFactory() as db:
        assert (
            await db.scalar(
                select(func.count())
                .select_from(WalletLedger)
                .where(
                    WalletLedger.wallet_id == wallet_id,
                    WalletLedger.entry_type == "adjustment",
                )
            )
            == 1
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "balance,confirmed,expected", [(495, False, 495), (495, True, 500), (-5, True, 0)]
)
async def test_confirmation_does_not_bypass_missing_consent_changed_balance_or_debt(
    balance, confirmed, expected
):
    uid, admin, rid, _ = await approved(balance)
    with pytest.raises(HTTPException) as error:
        await retry(admin, rid, confirmed, expected)
    assert error.value.status_code == 409
    async with SessionFactory() as db:
        assert (
            await db.scalar(select(Wallet).where(Wallet.driver_id == uid))
        ).balance_vnd == balance


@pytest.mark.asyncio
async def test_refund_and_queue_audit_rollback_together():
    uid, admin, rid, _ = await approved()
    from src.modules.privacy import service as module

    original = module.ghi_nhat_ky

    async def fail_queue(*args, **kwargs):
        if kwargs.get("action") == "privacy.execution_queued":
            raise RuntimeError("queue audit unavailable")
        return await original(*args, **kwargs)

    with (
        patch.object(module, "ghi_nhat_ky", side_effect=fail_queue),
        pytest.raises(RuntimeError, match="queue audit"),
    ):
        await retry(admin, rid)
    async with SessionFactory() as db:
        wallet = await db.scalar(select(Wallet).where(Wallet.driver_id == uid))
        assert wallet.balance_vnd == 495
        assert (
            await db.scalar(
                select(func.count())
                .select_from(WalletLedger)
                .where(
                    WalletLedger.wallet_id == wallet.id,
                    WalletLedger.entry_type == "adjustment",
                )
            )
            == 0
        )


@pytest.mark.asyncio
async def test_external_refund_does_not_bypass_legal_hold():
    uid, admin, rid, _ = await approved()
    async with SessionFactory() as db:
        await PrivacyRetentionService(db).set_legal_hold(
            uid, True, "Hold for test", admin, AUTH
        )
    with pytest.raises(HTTPException) as error:
        await retry(admin, rid)
    assert error.value.status_code == 409
    async with SessionFactory() as db:
        assert (
            await db.scalar(select(Wallet).where(Wallet.driver_id == uid))
        ).balance_vnd == 495
