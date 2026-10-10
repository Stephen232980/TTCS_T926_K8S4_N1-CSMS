import asyncio
import os
import subprocess
import sys
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
import pytest_asyncio
from psycopg import sql
from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.modules.identity.models import Role, User, UserRole
from src.modules.wallet.exceptions import (
    WalletAdjustmentAuditError,
    WalletAdminRequiredError,
    WalletAmountError,
    WalletLedgerConflictError,
    WalletLockedError,
    WalletNotFoundError,
)
from src.modules.wallet.models import Wallet, WalletAudit, WalletLedger
from src.modules.wallet.service import MAX_VND, ghi_so_cai, phuc_hoi_so_du_cache


async def setup_wallet(session, *, admin=False):
    user = User(email=f"t86-{uuid4()}@example.com", password_hash="unused")
    session.add(user)
    await session.flush()
    if admin:
        role = await session.scalar(select(Role).where(Role.code == "admin"))
        if role is None:
            role = Role(code="admin")
            session.add(role)
            await session.flush()
        session.add(UserRole(user_id=user.id, role_id=role.id))
    wallet = Wallet(driver_id=user.id)
    session.add(wallet)
    await session.flush()
    return user, wallet


async def post(session, wallet, amount=100, **overrides):
    values = {
        "wallet_id": wallet.id,
        "entry_type": "manual_topup" if amount > 0 else "charging_debit",
        "amount_vnd": amount,
        "reference_type": "test",
        "reference_id": str(uuid4()),
    }
    return await ghi_so_cai(session, **(values | overrides))


async def rows(session, wallet):
    return (
        await session.scalars(
            select(WalletLedger)
            .where(WalletLedger.wallet_id == wallet.id)
            .order_by(WalletLedger.id)
        )
    ).all()


async def authorize(session, wallet, actor, amount=20):
    audit = WalletAudit(
        wallet_id=wallet.id,
        actor_id=actor.id,
        action="adjustment_authorized",
        before_balance_vnd=wallet.balance_vnd,
        after_balance_vnd=wallet.balance_vnd + amount,
        amount_vnd=amount,
        reason="Verified correction",
    )
    session.add(audit)
    await session.flush()
    return audit


async def test_credit_debit_debt_and_idempotency(db_session):
    _, wallet = await setup_wallet(db_session)
    credit = await post(db_session, wallet, 5_000_000_000)
    for _ in range(5):
        replay = await post(
            db_session, wallet, 5_000_000_000, reference_id=credit.reference_id
        )
        assert replay.id == credit.id
    debit = await post(db_session, wallet, -6_000_000_000)
    assert wallet.balance_vnd == debit.balance_after_vnd == -1_000_000_000
    assert len(await rows(db_session, wallet)) == 2


@pytest.mark.parametrize("different_wallet", [False, True])
async def test_conflict_preserves_both_balances(db_session, different_wallet):
    _, wallet = await setup_wallet(db_session)
    _, other = await setup_wallet(db_session)
    original = await post(db_session, wallet)
    with pytest.raises(WalletLedgerConflictError):
        await post(
            db_session,
            other if different_wallet else wallet,
            100 if different_wallet else 101,
            reference_id=original.reference_id,
        )
    assert wallet.balance_vnd == 100 and other.balance_vnd == 0
    assert len(await rows(db_session, wallet)) == 1
    assert not await rows(db_session, other)


@pytest.mark.parametrize("amount", [True, 1.5, Decimal(100), 0, MAX_VND + 1])
async def test_invalid_money_changes_nothing(db_session, amount):
    _, wallet = await setup_wallet(db_session)
    with pytest.raises(WalletAmountError):
        await post(db_session, wallet, amount)
    assert wallet.balance_vnd == 0 and not await rows(db_session, wallet)


@pytest.mark.parametrize(
    ("kind", "amount"),
    [("manual_topup", -1), ("gateway_topup", -1), ("charging_debit", 1)],
)
async def test_wrong_sign_rejected(db_session, kind, amount):
    _, wallet = await setup_wallet(db_session)
    with pytest.raises(WalletAmountError):
        await post(db_session, wallet, amount, entry_type=kind)


async def test_balance_overflow_and_missing_wallet(db_session):
    _, wallet = await setup_wallet(db_session)
    await post(db_session, wallet, MAX_VND)
    with pytest.raises(WalletAmountError):
        await post(db_session, wallet, 1)
    assert wallet.balance_vnd == MAX_VND and len(await rows(db_session, wallet)) == 1
    with pytest.raises(WalletNotFoundError):
        await post(db_session, wallet, wallet_id=uuid4())


@pytest.mark.parametrize("kind", ["manual_topup", "gateway_topup", "charging_debit"])
async def test_locked_wallet_denies_normal_entries_and_replay(db_session, kind):
    _, wallet = await setup_wallet(db_session)
    amount = -10 if kind == "charging_debit" else 10
    original = await post(db_session, wallet, amount, entry_type=kind)
    wallet.status = "locked"
    await db_session.flush()
    for reference in [str(uuid4()), original.reference_id]:
        with pytest.raises(WalletLockedError):
            await post(
                db_session, wallet, amount, entry_type=kind, reference_id=reference
            )
    assert len(await rows(db_session, wallet)) == 1


async def test_locked_adjustment_requires_matching_admin_audit(db_session):
    admin, wallet = await setup_wallet(db_session, admin=True)
    wallet.status = "locked"
    await db_session.flush()
    audit = await authorize(db_session, wallet, admin)
    values = {
        "entry_type": "adjustment",
        "reference_type": "audit",
        "actor_id": admin.id,
    }
    with pytest.raises(WalletAdjustmentAuditError):
        await post(db_session, wallet, 20, reference_id=str(uuid4()), **values)
    with pytest.raises(WalletAdjustmentAuditError):
        await post(db_session, wallet, 21, reference_id=str(audit.id), **values)
    row = await post(db_session, wallet, 20, reference_id=str(audit.id), **values)
    second = await authorize(db_session, wallet, admin, -5)
    await post(db_session, wallet, -5, reference_id=str(second.id), **values)
    replay = await post(db_session, wallet, 20, reference_id=str(audit.id), **values)
    assert row.id == replay.id
    assert wallet.balance_vnd == 15 and wallet.status == "locked"
    assert len(await rows(db_session, wallet)) == 2


@pytest.mark.parametrize("inactive", [False, True])
async def test_adjustment_and_repair_reject_nonadmin_or_inactive(db_session, inactive):
    user, wallet = await setup_wallet(db_session, admin=inactive)
    if inactive:
        user.status = "suspended"
        await db_session.flush()
    audit = await authorize(db_session, wallet, user)
    with pytest.raises(WalletAdminRequiredError):
        await post(
            db_session,
            wallet,
            20,
            entry_type="adjustment",
            reference_type="audit",
            reference_id=str(audit.id),
            actor_id=user.id,
        )
    with pytest.raises(WalletAdminRequiredError):
        await phuc_hoi_so_du_cache(
            db_session, wallet_id=wallet.id, actor_id=user.id, reason="Repair"
        )
    assert wallet.balance_vnd == 0 and not await rows(db_session, wallet)


async def test_stale_adjustment_audit_rejected(db_session):
    admin, wallet = await setup_wallet(db_session, admin=True)
    audit = await authorize(db_session, wallet, admin)
    await post(db_session, wallet, 100)
    with pytest.raises(WalletAdjustmentAuditError, match="stale"):
        await post(
            db_session,
            wallet,
            20,
            entry_type="adjustment",
            reference_type="audit",
            reference_id=str(audit.id),
            actor_id=admin.id,
        )
    assert wallet.balance_vnd == 100 and len(await rows(db_session, wallet)) == 1


@pytest.mark.parametrize(
    "overrides",
    [
        {"reference_id": " "},
        {"reference_type": " "},
        {"reference_id": "x" * 129},
        {"reference_type": "x" * 51},
        {"reference_id": None},
        {"entry_type": "unknown"},
    ],
)
async def test_invalid_reference_or_type(db_session, overrides):
    _, wallet = await setup_wallet(db_session)
    with pytest.raises((ValueError, TypeError)):
        await post(db_session, wallet, **overrides)
    assert wallet.balance_vnd == 0 and not await rows(db_session, wallet)


@pytest.mark.parametrize("wrong_field", ["wallet", "actor", "reference_type"])
async def test_adjustment_audit_cannot_be_reused_for_different_operation(
    db_session, wrong_field
):
    admin, wallet = await setup_wallet(db_session, admin=True)
    other_admin, other_wallet = await setup_wallet(db_session, admin=True)
    audit = await authorize(db_session, wallet, admin)
    with pytest.raises(WalletAdjustmentAuditError):
        await post(
            db_session,
            other_wallet if wrong_field == "wallet" else wallet,
            20,
            entry_type="adjustment",
            reference_id=str(audit.id),
            reference_type="test" if wrong_field == "reference_type" else "audit",
            actor_id=other_admin.id if wrong_field == "actor" else admin.id,
        )
    assert wallet.balance_vnd == other_wallet.balance_vnd == 0


async def test_repair_negative_balance_and_empty_ledger(db_session):
    admin, wallet = await setup_wallet(db_session, admin=True)
    wallet.balance_vnd = 10
    await db_session.flush()
    await phuc_hoi_so_du_cache(
        db_session, wallet_id=wallet.id, actor_id=admin.id, reason="Empty"
    )
    assert wallet.balance_vnd == 0
    await post(db_session, wallet, -50)
    wallet.balance_vnd = 10
    await db_session.flush()
    await phuc_hoi_so_du_cache(
        db_session, wallet_id=wallet.id, actor_id=admin.id, reason="Debt"
    )
    assert wallet.balance_vnd == -50 and len(await rows(db_session, wallet)) == 1


async def test_repair_overflow_does_not_change_cache_or_create_audit(db_session):
    admin, wallet = await setup_wallet(db_session, admin=True)
    # Simulate inconsistent historical data whose total exceeds BIGINT.
    for amount in [MAX_VND, 1]:
        db_session.add(
            WalletLedger(
                wallet_id=wallet.id,
                entry_type="manual_topup",
                amount_vnd=amount,
                balance_after_vnd=0,
                reference_type="test",
                reference_id=str(uuid4()),
            )
        )
    await db_session.flush()
    with pytest.raises(WalletAmountError):
        await phuc_hoi_so_du_cache(
            db_session, wallet_id=wallet.id, actor_id=admin.id, reason="Overflow"
        )
    assert wallet.balance_vnd == 0
    assert await db_session.scalar(select(func.count()).select_from(WalletAudit)) == 0


async def test_runtime_role_can_append_audit_but_cannot_rewrite_it(db_session):
    admin, wallet = await setup_wallet(db_session, admin=True)
    audit = await authorize(db_session, wallet, admin)
    role = "t86_runtime_" + uuid4().hex
    await db_session.execute(
        text(f'CREATE ROLE "{role}" NOLOGIN NOSUPERUSER NOINHERIT')
    )
    grants = Path("scripts/grant_wallet_ledger.sql").read_text(encoding="utf-8")
    grants = "\n".join(
        line for line in grants.splitlines() if not line.startswith(("--", "\\"))
    )
    for statement in grants.replace(':"app_role"', f'"{role}"').split(";"):
        if statement.strip() and statement.strip() not in ("BEGIN", "COMMIT"):
            await db_session.execute(text(statement))
    async with db_session.begin_nested():
        await db_session.execute(text(f'SET LOCAL ROLE "{role}"'))
        assert (
            await db_session.scalar(
                text("SELECT reason FROM wallet_audits WHERE id = :id"),
                {"id": audit.id},
            )
            == audit.reason
        )
        await db_session.execute(
            text("""INSERT INTO wallet_audits
            (id, wallet_id, actor_id, action, before_balance_vnd, after_balance_vnd, reason)
            VALUES (:id, :wallet, :actor, 'cache_repaired', 10, 0, 'Repair')"""),
            {"id": uuid4(), "wallet": wallet.id, "actor": admin.id},
        )
        for statement in [
            "UPDATE wallet_audits SET reason = 'bad'",
            "DELETE FROM wallet_audits",
            "TRUNCATE wallet_audits",
        ]:
            with pytest.raises(DBAPIError, match="permission denied"):
                async with db_session.begin_nested():
                    await db_session.execute(text(statement))
        await db_session.execute(text("RESET ROLE"))


async def test_foreign_key_failure_preserves_outer_transaction(db_session):
    _, wallet = await setup_wallet(db_session)
    with pytest.raises(IntegrityError):
        await post(db_session, wallet, actor_id=uuid4())
    assert wallet.balance_vnd == 0 and not await rows(db_session, wallet)
    await post(db_session, wallet, 10)
    assert wallet.balance_vnd == 10


async def test_cache_repair_has_audit_without_fake_money_and_never_unlocks(db_session):
    admin, wallet = await setup_wallet(db_session, admin=True)
    await post(db_session, wallet, 80_000)
    wallet.balance_vnd = 100_000  # Inject a cache defect, not a monetary operation.
    wallet.status = "locked"
    await db_session.flush()
    for _ in range(2):
        repaired = await phuc_hoi_so_du_cache(
            db_session, wallet_id=wallet.id, actor_id=admin.id, reason=" Reconcile "
        )
        assert repaired.balance_vnd == 80_000 and repaired.status == "locked"
    audits = (await db_session.scalars(select(WalletAudit))).all()
    assert len(audits) == 1
    assert (audits[0].before_balance_vnd, audits[0].after_balance_vnd) == (
        100_000,
        80_000,
    )
    assert audits[0].amount_vnd is None and audits[0].reason == "Reconcile"
    assert len(await rows(db_session, wallet)) == 1


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE wallet_audits SET reason = 'tampered'",
        "DELETE FROM wallet_audits",
        "TRUNCATE wallet_audits",
    ],
)
async def test_audit_is_append_only(db_session, statement):
    admin, wallet = await setup_wallet(db_session, admin=True)
    await authorize(db_session, wallet, admin)
    with pytest.raises(DBAPIError, match="append-only"):
        async with db_session.begin_nested():
            await db_session.execute(text(statement))


async def test_audit_migration_round_trip_preserves_wallet_and_ledger(
    isolated_wallet_db,
):
    factory = isolated_wallet_db
    async with factory() as session:
        admin, wallet = await setup_wallet(session, admin=True)
        await post(session, wallet, 80)
        await authorize(session, wallet, admin)
        await session.commit()
    test_url = factory.kw["bind"].url.render_as_string(hide_password=False)
    await asyncio.to_thread(
        subprocess.run,
        [sys.executable, "-m", "alembic", "downgrade", "a080009a2026"],
        env=os.environ | {"DATABASE_URL": test_url},
        check=True,
        capture_output=True,
    )
    async with factory() as session:
        assert await session.scalar(text("SELECT to_regclass('wallet_audits')")) is None
        assert (await session.get(Wallet, wallet.id)).balance_vnd == 80
        assert len(await rows(session, wallet)) == 1
        with pytest.raises(DBAPIError, match="append-only"):
            async with session.begin_nested():
                await session.execute(text("UPDATE wallet_ledger SET amount_vnd = 81"))
    await asyncio.to_thread(
        subprocess.run,
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        env=os.environ | {"DATABASE_URL": test_url},
        check=True,
        capture_output=True,
    )
    async with factory() as session:
        assert (
            await session.scalar(text("SELECT to_regclass('wallet_audits')"))
            == "wallet_audits"
        )
        assert (await session.get(Wallet, wallet.id)).balance_vnd == 80
        assert len(await rows(session, wallet)) == 1


@pytest_asyncio.fixture
async def isolated_wallet_db():
    """Committed concurrency tests own a database; never delete immutable evidence."""
    url = make_url(os.environ["DATABASE_URL"])
    database = "t86_" + uuid4().hex
    admin_url = url.set(drivername="postgresql", database="postgres")
    with psycopg.connect(
        admin_url.render_as_string(hide_password=False), autocommit=True
    ) as connection:
        connection.execute(
            sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database))
        )
    test_url = url.set(database=database).render_as_string(hide_password=False)
    engine = create_async_engine(test_url)
    try:
        await asyncio.to_thread(
            subprocess.run,
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            env=os.environ | {"DATABASE_URL": test_url},
            check=True,
            capture_output=True,
        )
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()
        with psycopg.connect(
            admin_url.render_as_string(hide_password=False), autocommit=True
        ) as connection:
            connection.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(
                    sql.Identifier(database)
                )
            )


async def test_two_connections_100_writes_without_lost_updates(isolated_wallet_db):
    factory = isolated_wallet_db
    async with factory() as session:
        _, wallet = await setup_wallet(session)
        wallet_id = wallet.id
        await session.commit()
    ready = asyncio.Barrier(2)

    async def worker(amount):
        async with factory() as session:
            pid = await session.scalar(text("SELECT pg_backend_pid()"))
            await ready.wait()
            for number in range(50):
                await ghi_so_cai(
                    session,
                    wallet_id=wallet_id,
                    entry_type="manual_topup" if amount > 0 else "charging_debit",
                    amount_vnd=amount,
                    reference_type="test",
                    reference_id=f"{pid}-{number}",
                )
                await session.commit()
            return pid

    pids = await asyncio.wait_for(asyncio.gather(worker(100), worker(-30)), 30)
    assert len(set(pids)) == 2
    async with factory() as session:
        wallet = await session.get(Wallet, wallet_id)
        ledger = await rows(session, wallet)
        assert len(ledger) == 100 and wallet.balance_vnd == 3500
        running = 0
        for row in ledger:
            running += row.amount_vnd
            assert row.balance_after_vnd == running


async def test_no_internal_commit_and_caller_rollback(isolated_wallet_db):
    factory = isolated_wallet_db
    async with factory() as setup:
        admin, wallet = await setup_wallet(setup, admin=True)
        await setup.commit()
    async with factory() as writer, factory() as reader:
        await post(writer, wallet, 80_000)
        assert await reader.scalar(select(func.count()).select_from(WalletLedger)) == 0
        assert (await reader.get(Wallet, wallet.id)).balance_vnd == 0
        await writer.rollback()
        assert await writer.scalar(select(func.count()).select_from(WalletLedger)) == 0
        local = await writer.get(Wallet, wallet.id)
        local.balance_vnd = 100_000
        await writer.flush()
        await phuc_hoi_so_du_cache(
            writer, wallet_id=wallet.id, actor_id=admin.id, reason="Repair"
        )
        assert await writer.scalar(select(func.count()).select_from(WalletAudit)) == 1
        await writer.rollback()
        assert await writer.scalar(select(func.count()).select_from(WalletAudit)) == 0
        assert (await writer.get(Wallet, wallet.id)).balance_vnd == 0


async def test_cross_wallet_key_race_is_business_conflict(isolated_wallet_db):
    factory = isolated_wallet_db
    async with factory() as setup:
        _, first = await setup_wallet(setup)
        _, second = await setup_wallet(setup)
        await setup.commit()
    async with factory() as writer, factory() as loser, factory() as observer:
        key = str(uuid4())
        await post(writer, first, reference_id=key)
        loser_pid = await loser.scalar(text("SELECT pg_backend_pid()"))
        task = asyncio.create_task(post(loser, second, reference_id=key))
        try:
            async with asyncio.timeout(10):
                while not await observer.scalar(
                    text("SELECT cardinality(pg_blocking_pids(:pid)) > 0"),
                    {"pid": loser_pid},
                ):
                    await asyncio.sleep(0.01)
            await writer.commit()
            with pytest.raises(WalletLedgerConflictError):
                await asyncio.wait_for(task, 10)
            assert (await loser.get(Wallet, second.id)).balance_vnd == 0
            await post(loser, second, 7)
            await loser.commit()
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        assert len(await rows(observer, first)) == 1
        assert len(await rows(observer, second)) == 1


async def test_cached_orm_balance_refreshed_after_lock(isolated_wallet_db):
    factory = isolated_wallet_db
    async with factory() as setup:
        _, wallet = await setup_wallet(setup)
        await setup.commit()
    async with factory() as stale, factory() as writer:
        cached = await stale.get(Wallet, wallet.id)
        assert cached.balance_vnd == 0
        await post(writer, wallet, 100)
        await writer.commit()
        await post(stale, cached, 20)
        assert cached.balance_vnd == 120


async def test_cache_repair_waits_for_writer_and_reads_committed_ledger(
    isolated_wallet_db,
):
    factory = isolated_wallet_db
    async with factory() as setup:
        admin, wallet = await setup_wallet(setup, admin=True)
        await setup.commit()
    async with factory() as writer, factory() as repair, factory() as observer:
        await repair.get(Wallet, wallet.id)
        await post(writer, wallet, 80)
        pid = await repair.scalar(text("SELECT pg_backend_pid()"))
        task = asyncio.create_task(
            phuc_hoi_so_du_cache(
                repair, wallet_id=wallet.id, actor_id=admin.id, reason="Reconcile"
            )
        )
        try:
            async with asyncio.timeout(10):
                while not await observer.scalar(
                    text("SELECT cardinality(pg_blocking_pids(:pid)) > 0"), {"pid": pid}
                ):
                    await asyncio.sleep(0.01)
            await writer.commit()
            repaired = await asyncio.wait_for(task, 10)
            assert repaired.balance_vnd == 80
            assert (
                await repair.scalar(select(func.count()).select_from(WalletAudit)) == 0
            )
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
