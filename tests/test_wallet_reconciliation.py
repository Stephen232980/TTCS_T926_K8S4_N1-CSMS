import asyncio
import logging
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select, text

from src.config import settings
from src.modules.billing.models import Invoice
from src.modules.charging.models import ChargingSession
from src.modules.wallet import reconciliation
from src.modules.wallet.models import Wallet, WalletLedger
from src.platform.audit.models import AuditLog
from tests.test_charging_sessions import setup, start
from tests.test_wallet_service import isolated_wallet_db as _isolated_database
from tests.test_wallet_service import post, setup_wallet

isolated_wallet_db = _isolated_database


async def invoice_wallet(session, settlement="debited", total=200):
    station, _, _, driver, _, conn, tag = await setup(session)
    tid = (await start(session, conn, tag)).payload["transactionId"]
    charging = await session.get(ChargingSession, tid)
    if settlement:
        charging.settlement_reason = settlement
        charging.settlement_completed_at = datetime.now(UTC)
    invoice = Invoice(
        session_id=tid,
        driver_id=driver.id,
        station_id=station.id,
        total_vnd=total,
        rounding_rule="Round then sum",
    )
    wallet = Wallet(driver_id=driver.id)
    session.add_all([invoice, wallet])
    await session.flush()
    return wallet, invoice


async def debit(session, wallet, invoice, **overrides):
    row = WalletLedger(
        wallet_id=wallet.id,
        entry_type="charging_debit",
        reference_type="charging_session",
        reference_id=str(invoice.session_id),
        amount_vnd=-invoice.total_vnd,
        balance_after_vnd=-invoice.total_vnd,
    )
    for name, value in overrides.items():
        setattr(row, name, value)
    session.add(row)
    await session.flush()
    wallet.balance_vnd += row.amount_vnd
    await session.flush()
    return row


async def test_cache_drift_locks_once_and_healthy_wallet_is_untouched(db_session):
    _, wallet = await setup_wallet(db_session)
    _, healthy = await setup_wallet(db_session)
    await post(db_session, wallet, 100)
    await db_session.execute(
        text("UPDATE wallets SET balance_vnd=101 WHERE id=:id"), {"id": wallet.id}
    )
    locked = await reconciliation.doi_chieu_so_du(db_session)
    assert wallet.id in locked and healthy.id not in locked
    assert wallet.status == "locked" and healthy.status == "active"
    audit = await db_session.scalar(
        select(AuditLog).where(
            AuditLog.object_type == "wallet", AuditLog.object_id == str(wallet.id)
        )
    )
    assert audit.actor_id is None and audit.action == "wallet.reconciliation_locked"
    assert audit.data == {
        "reasons": ["balance_mismatch"],
        "balance_vnd": 101,
        "ledger_total_vnd": 100,
    }
    assert await reconciliation.doi_chieu_so_du(db_session) == []
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(
                AuditLog.object_type == "wallet", AuditLog.object_id == str(wallet.id)
            )
        )
        == 1
    )
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(WalletLedger)
            .where(WalletLedger.wallet_id == wallet.id)
        )
        == 1
    )


@pytest.mark.parametrize(
    "case",
    [
        "missing",
        "duplicate",
        "wrong_wallet",
        "wrong_amount",
        "wrong_type",
        "wrong_reference_type",
        "wrong_reference_id",
    ],
)
async def test_debited_invoice_errors_are_detected_even_when_cache_matches(
    db_session, case
):
    wallet, invoice = await invoice_wallet(db_session)
    _, other = await setup_wallet(db_session)
    if case == "duplicate":
        # Model a corrupt historical ledger; outer test rollback restores UNIQUE.
        await db_session.execute(
            text("ALTER TABLE wallet_ledger DROP CONSTRAINT uq_wallet_ledger_reference")
        )
        await debit(db_session, wallet, invoice)
        await debit(db_session, wallet, invoice)
    elif case != "missing":
        overrides = {
            "wrong_amount": {"amount_vnd": -199},
            "wrong_type": {"entry_type": "manual_topup"},
            "wrong_reference_type": {"reference_type": "invoice"},
            "wrong_reference_id": {"reference_id": str(invoice.id)},
        }.get(case, {})
        await debit(
            db_session,
            other if case == "wrong_wallet" else wallet,
            invoice,
            **overrides,
        )
    locked = await reconciliation.doi_chieu_so_du(db_session)
    assert wallet.id in locked
    if case == "wrong_wallet":
        assert other.id in locked
    rows = (
        await db_session.scalars(
            select(AuditLog).where(
                AuditLog.object_type == "wallet",
                AuditLog.object_id.in_([str(wallet.id), str(other.id)]),
            )
        )
    ).all()
    assert len(rows) == (2 if case == "wrong_wallet" else 1)
    assert all("balance_mismatch" not in row.data["reasons"] for row in rows)
    assert all(row.data["reasons"] for row in rows)
    assert await reconciliation.doi_chieu_so_du(db_session) == []


@pytest.mark.parametrize(
    "settlement", ["debited", "zero_invoice", "legacy_exempt", None]
)
async def test_valid_invoice_or_exempt_unsettled_wallet_is_not_locked(
    db_session, settlement
):
    wallet, invoice = await invoice_wallet(db_session, settlement=settlement)
    if settlement == "debited":
        await debit(db_session, wallet, invoice)
    assert await reconciliation.doi_chieu_so_du(db_session, wallet_id=wallet.id) == []
    assert wallet.status == "active"
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(
                AuditLog.object_type == "wallet", AuditLog.object_id == str(wallet.id)
            )
        )
        == 0
    )


async def test_job_audit_failure_rolls_back_lock(db_session, monkeypatch):
    _, wallet = await setup_wallet(db_session)
    wallet.balance_vnd = 1
    await db_session.flush()
    original = reconciliation.ghi_nhat_ky

    async def fail(session, **kwargs):
        await original(session, **kwargs)
        raise RuntimeError("audit failure")

    monkeypatch.setattr(reconciliation, "ghi_nhat_ky", fail)
    with pytest.raises(RuntimeError):
        await reconciliation.doi_chieu_so_du(db_session, wallet_id=wallet.id)
    await db_session.refresh(wallet)
    assert wallet.status == "active"
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(
                AuditLog.object_type == "wallet", AuditLog.object_id == str(wallet.id)
            )
        )
        == 0
    )


async def test_writer_lock_is_skipped_then_committed_balance_is_checked(
    isolated_wallet_db,
):
    factory = isolated_wallet_db
    async with factory() as session:
        _, wallet = await setup_wallet(session)
        await session.commit()
    async with factory() as writer, factory() as checker:
        await post(writer, wallet, 100)
        assert await asyncio.wait_for(reconciliation.doi_chieu_so_du(checker), 2) == []
        await checker.commit()
        await writer.commit()
        assert await reconciliation.doi_chieu_so_du(checker) == []
        assert await checker.scalar(select(func.count()).select_from(AuditLog)) == 0


async def test_runner_warns_only_once_after_committed_lock(
    isolated_wallet_db, monkeypatch, caplog
):
    factory = isolated_wallet_db
    async with factory() as session:
        _, wallet = await setup_wallet(session)
        wallet.balance_vnd = 1
        await session.commit()
    monkeypatch.setattr(reconciliation, "SessionFactory", factory)
    with caplog.at_level(logging.WARNING, logger="csms.wallet"):
        assert await reconciliation.run_reconciliation() == 1
        assert await reconciliation.run_reconciliation() == 0
    warnings = [
        r for r in caplog.records if r.msg.startswith("wallet_reconciliation_locked")
    ]
    assert len(warnings) == 1 and str(wallet.id) in warnings[0].getMessage()


async def test_loop_uses_configured_interval_and_cancels_cleanly(monkeypatch):
    waits = []

    async def sleep(seconds):
        waits.append(seconds)
        if len(waits) == 2:
            raise asyncio.CancelledError

    from unittest.mock import AsyncMock

    monkeypatch.setattr(settings, "wallet_reconciliation_interval_seconds", 123)
    monkeypatch.setattr(reconciliation.asyncio, "sleep", sleep)
    run = AsyncMock(return_value=0)
    monkeypatch.setattr(reconciliation, "run_reconciliation", run)
    with pytest.raises(asyncio.CancelledError):
        await reconciliation.reconciliation_loop()
    assert waits == [123, 123]
    run.assert_awaited_once()


async def test_runner_failure_before_commit_emits_no_lock_warning(
    isolated_wallet_db, monkeypatch, caplog
):
    from sqlalchemy.exc import SQLAlchemyError

    factory = isolated_wallet_db
    async with factory() as session:
        _, wallet = await setup_wallet(session)
        wallet.balance_vnd = 1
        await session.commit()
    original = reconciliation.doi_chieu_so_du

    async def fail(session, **kwargs):
        await original(session, **kwargs)
        raise SQLAlchemyError("injected failure")

    monkeypatch.setattr(reconciliation, "SessionFactory", factory)
    monkeypatch.setattr(reconciliation, "doi_chieu_so_du", fail)
    with caplog.at_level(logging.WARNING, logger="csms.wallet"):
        assert await reconciliation.run_reconciliation() == 0
    assert not any(
        r.msg.startswith("wallet_reconciliation_locked") for r in caplog.records
    )
    async with factory() as session:
        assert (await session.get(Wallet, wallet.id)).status == "active"
        assert await session.scalar(select(func.count()).select_from(AuditLog)) == 0


async def test_application_lifespan_starts_and_cancels_wallet_job(monkeypatch):
    from contextlib import asynccontextmanager

    from src.entrypoints import lifecycle

    entered = asyncio.Event()
    cancelled = asyncio.Event()

    @asynccontextmanager
    async def ocpp(app):
        yield

    async def loop():
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    monkeypatch.setattr(lifecycle, "ocpp_lifespan", ocpp)
    monkeypatch.setattr(lifecycle, "reconciliation_loop", loop)
    async with lifecycle.application_lifespan(None):
        await asyncio.wait_for(entered.wait(), 1)
    assert cancelled.is_set()
