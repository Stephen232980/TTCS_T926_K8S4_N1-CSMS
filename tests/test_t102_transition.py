"""Real PostgreSQL transition revision and corrupt-ledger acceptance cases."""

import importlib
import logging
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import event, select

from src.modules.billing import closure
from src.modules.billing.invoicing import lap_hoa_don
from src.modules.billing.models import Invoice
from src.modules.charging.models import ChargingSession
from src.modules.wallet.models import Wallet, WalletLedger
from src.modules.wallet.service import tru_vi
from tests.test_effective_tariffs import committed_tariff_db as isolated_db
from tests.test_t80_invoicing import seed

committed_tariff_db = isolated_db

revision = importlib.import_module(
    "migrations.versions.4db8d8987c3a_t102_legacy_exempt_settlement"
)
CUTOFF = datetime(2000, 1, 1, tzinfo=UTC)


async def invoiced(factory, stamp, *, ledger=None):
    def timestamp(_mapper, _connection, invoice):
        invoice.created_at = stamp

    event.listen(Invoice, "before_insert", timestamp)
    try:
        async with factory() as db, db.begin():
            charging, *_ = await seed(db)
            result = await lap_hoa_don(db, charging.id)
            wallet = await db.scalar(
                select(Wallet).where(Wallet.driver_id == result.invoice.driver_id)
            )
            if ledger == "valid":
                await tru_vi(db, invoice=result.invoice)
            elif ledger is not None:
                amount = -result.invoice.total_vnd
                target_wallet_id = wallet.id
                if ledger == "wallet":
                    _, _, other_driver, _ = await seed(db)
                    target_wallet_id = await db.scalar(
                        select(Wallet.id).where(Wallet.driver_id == other_driver.id)
                    )
                wallet.balance_vnd += amount
                db.add(
                    WalletLedger(
                        wallet_id=target_wallet_id,
                        entry_type="manual_topup"
                        if ledger == "type"
                        else "charging_debit",
                        amount_vnd=amount if ledger != "amount" else amount - 1,
                        balance_after_vnd=wallet.balance_vnd,
                        reference_type=(
                            "wrong_reference"
                            if ledger == "reference"
                            else "charging_session"
                        ),
                        reference_id=str(charging.id),
                    )
                )
            return charging.id, wallet.id, wallet.balance_vnd, result.invoice.total_vnd
    finally:
        event.remove(Invoice, "before_insert", timestamp)


async def upgrade(factory, monkeypatch, cutoff):
    monkeypatch.setattr(revision, "get_cutoff_iso", lambda: cutoff)
    async with factory() as db, db.begin():
        connection = await db.connection()

        def run(sync_connection):
            monkeypatch.setattr(revision.op, "get_bind", lambda: sync_connection)
            revision.upgrade()

        await connection.run_sync(run)


async def test_actual_revision_boundaries_existing_debit_and_review(
    committed_tariff_db, monkeypatch, caplog
):
    factory = committed_tariff_db
    monkeypatch.setattr(closure, "SessionFactory", factory)
    before = await invoiced(factory, CUTOFF - timedelta(seconds=1))
    exact = await invoiced(factory, CUTOFF)
    after = await invoiced(factory, CUTOFF + timedelta(seconds=1))
    valid = await invoiced(factory, CUTOFF - timedelta(seconds=1), ledger="valid")
    wrong_ref = await invoiced(
        factory, CUTOFF - timedelta(seconds=1), ledger="reference"
    )
    wrong_amount = await invoiced(
        factory, CUTOFF - timedelta(seconds=1), ledger="amount"
    )
    with caplog.at_level(logging.INFO, logger="alembic.runtime.migration"):
        await upgrade(factory, monkeypatch, CUTOFF.isoformat())
    assert "legacy_exempt=1 debited=1 needs_review=2" in caplog.text
    assert "database=t68_" in caplog.text
    assert CUTOFF.isoformat() in caplog.text
    async with factory() as db:
        for case, expected in ((before, "legacy_exempt"), (valid, "debited")):
            charging = await db.get(ChargingSession, case[0])
            assert charging.settlement_reason == expected
            assert charging.settlement_completed_at is not None
        for case in (exact, after, wrong_ref, wrong_amount):
            charging = await db.get(ChargingSession, case[0])
            assert charging.settlement_reason is None
            assert charging.settlement_completed_at is None
            assert bool(charging.review_reasons) == (case in (wrong_ref, wrong_amount))

    result = await closure.scan_unsettled_sessions(settle=True)
    assert result.ready == 2 and result.needs_review == 2
    await closure.scan_unsettled_sessions(settle=True)
    async with factory() as db:
        for case in (before, exact, after, valid, wrong_ref, wrong_amount):
            wallet = await db.get(Wallet, case[1])
            expected = case[2] - case[3] if case in (exact, after) else case[2]
            assert wallet.balance_vnd == expected
            rows = list(
                await db.scalars(
                    select(WalletLedger).where(
                        WalletLedger.reference_id == str(case[0])
                    )
                )
            )
            assert len(rows) == (0 if case == before else 1)


@pytest.mark.parametrize("cutoff", [None, "", "not-a-date", "2000-01-01T00:00:00"])
async def test_invalid_cutoff_fails_before_any_write(
    committed_tariff_db, monkeypatch, cutoff
):
    case = await invoiced(committed_tariff_db, CUTOFF - timedelta(seconds=1))
    with pytest.raises(ValueError):
        await upgrade(committed_tariff_db, monkeypatch, cutoff)
    async with committed_tariff_db() as db:
        charging = await db.get(ChargingSession, case[0])
        assert charging.settlement_completed_at is None
        assert charging.settlement_reason is None
        assert charging.review_reasons == []
        wallet = await db.get(Wallet, case[1])
        assert wallet.balance_vnd == case[2]


@pytest.mark.parametrize("ledger", ["reference", "amount", "type", "wallet"])
async def test_runtime_corrupt_ledger_stays_review_without_debit(
    committed_tariff_db, monkeypatch, ledger
):
    factory = committed_tariff_db
    monkeypatch.setattr(closure, "SessionFactory", factory)
    case = await invoiced(factory, CUTOFF, ledger=ledger)
    for _ in range(2):
        result = await closure.chot_phien(case[0], settle=True)
        assert result.status == "needs_review"
    async with factory() as db:
        charging = await db.get(ChargingSession, case[0])
        assert charging.settlement_completed_at is None
        assert charging.settlement_reason is None
        assert charging.review_reasons == ["settlement_ledger_mismatch"]
        wallet = await db.get(Wallet, case[1])
        assert wallet.balance_vnd == case[2]


def test_cutoff_configuration_precedence(monkeypatch):
    monkeypatch.setattr(revision.context, "get_x_argument", lambda **_: {})
    monkeypatch.setattr(revision.settings, "legacy_settlement_cutoff", "settings-value")
    monkeypatch.delenv("LEGACY_SETTLEMENT_CUTOFF", raising=False)
    assert revision.get_cutoff_iso() == "settings-value"
    monkeypatch.setenv("LEGACY_SETTLEMENT_CUTOFF", "environment-value")
    assert revision.get_cutoff_iso() == "environment-value"
    monkeypatch.setattr(
        revision.context, "get_x_argument", lambda **_: {"legacy_cutoff": "cli-value"}
    )
    assert revision.get_cutoff_iso() == "cli-value"


async def test_runtime_existing_valid_debit_not_charged_again(
    committed_tariff_db, monkeypatch
):
    factory = committed_tariff_db
    monkeypatch.setattr(closure, "SessionFactory", factory)
    case = await invoiced(factory, CUTOFF, ledger="valid")
    # Recognition of a historical valid debit does not write money, even if locked.
    async with factory() as db, db.begin():
        wallet = await db.get(Wallet, case[1])
        wallet.status = "locked"
    for _ in range(2):
        assert (await closure.chot_phien(case[0], settle=True)).status == "ready"
    async with factory() as db:
        charging = await db.get(ChargingSession, case[0])
        assert charging.settlement_reason == "debited"
        wallet = await db.get(Wallet, case[1])
        assert wallet.balance_vnd == case[2]


async def test_failure_after_real_wallet_write_rolls_back_everything(
    committed_tariff_db, monkeypatch
):
    factory = committed_tariff_db
    monkeypatch.setattr(closure, "SessionFactory", factory)
    async with factory() as db, db.begin():
        charging, _, driver, _ = await seed(db)
        session_id = charging.id
        wallet = await db.scalar(select(Wallet).where(Wallet.driver_id == driver.id))
        wallet_id, balance = wallet.id, wallet.balance_vnd

    async def fail_after_debit(db, **kwargs):
        await tru_vi(db, **kwargs)
        raise RuntimeError("controlled failure after debit flush")

    monkeypatch.setattr(closure, "tru_vi", fail_after_debit)
    with pytest.raises(RuntimeError):
        await closure.chot_phien(session_id, settle=True)
    async with factory() as db:
        assert (
            await db.scalar(select(Invoice.id).where(Invoice.session_id == session_id))
            is None
        )
        assert (
            await db.scalar(
                select(WalletLedger.id).where(
                    WalletLedger.reference_id == str(session_id)
                )
            )
            is None
        )
        assert (await db.get(Wallet, wallet_id)).balance_vnd == balance
        charging = await db.get(ChargingSession, session_id)
        assert charging.settlement_completed_at is None
        assert charging.settlement_reason is None
    monkeypatch.setattr(closure, "tru_vi", tru_vi)
    result = await closure.scan_unsettled_sessions(settle=True)
    assert result.ready == 1
    assert (await closure.scan_unsettled_sessions(settle=True)).scanned == 0
