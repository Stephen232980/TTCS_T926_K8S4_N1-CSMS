import asyncio
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, text

from src.entrypoints.http import app
from src.modules.identity.authorization import CurrentActor
from src.modules.identity.dependencies import get_current_actor
from src.modules.wallet import administration, service
from src.modules.wallet.administration import dieu_chinh_vi, mo_khoa_vi, sua_so_du_cache
from src.modules.wallet.exceptions import (
    WalletAdjustmentAuditError,
    WalletAmountError,
    WalletReconciliationError,
)
from src.modules.wallet.models import Wallet, WalletAudit, WalletLedger
from src.modules.wallet.reconciliation import doi_chieu_so_du
from src.platform.audit.models import AuditLog
from tests.test_manual_topup import api_db as _api_database
from tests.test_wallet_reconciliation import invoice_wallet
from tests.test_wallet_service import isolated_wallet_db as _isolated_database
from tests.test_wallet_service import post, setup_wallet

api_db = _api_database
isolated_wallet_db = _isolated_database


async def request(wallet_id, command, actor=None, body=None):
    if actor is not None:
        app.dependency_overrides[get_current_actor] = lambda: actor
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.post(
                f"/api/v1/admin/wallets/{wallet_id}/{command}", json=body
            )
    finally:
        app.dependency_overrides.pop(get_current_actor, None)


@pytest.mark.parametrize("command", ["repair-cache", "unlock", "adjustments"])
@pytest.mark.parametrize(
    "role", [None, "operator", "accountant", "driver", "station_owner"]
)
async def test_only_admin_can_run_commands(command, role):
    actor = CurrentActor(uuid4(), frozenset({role})) if role else None
    body = (
        {"reason": "Checked", "amount_vnd": 1, "audit_id": str(uuid4())}
        if command == "adjustments"
        else {"reason": "Checked"}
    )
    response = await request(uuid4(), command, actor, body)
    assert response.status_code == (403 if role else 401)


async def test_cache_repair_then_unlock_has_no_adjustment_and_exact_audit(api_db):
    factory, actor, _, wallet_id = api_db
    async with factory() as session:
        wallet = await session.get(Wallet, wallet_id)
        await post(session, wallet, 100)
        wallet.balance_vnd = 101
        await session.commit()
    async with factory() as session, session.begin():
        assert await doi_chieu_so_du(session, wallet_id=wallet_id) == [wallet_id]
    response = await request(wallet_id, "unlock", actor)
    assert response.status_code == 409
    assert response.json()["detail"]["checks"] == ["balance_mismatch"]
    repaired = await request(
        wallet_id, "repair-cache", actor, {"reason": "Verified ledger"}
    )
    assert repaired.status_code == 200
    assert (
        repaired.json()["balance_vnd"] == 100 and repaired.json()["status"] == "locked"
    )
    assert (await request(wallet_id, "unlock", actor)).json()["status"] == "active"
    assert (await request(wallet_id, "unlock", actor)).status_code == 200
    assert (
        await request(wallet_id, "repair-cache", actor, {"reason": "No change"})
    ).status_code == 200
    async with factory() as session:
        ledger = (
            await session.scalars(
                select(WalletLedger).where(WalletLedger.wallet_id == wallet_id)
            )
        ).all()
        assert len(ledger) == 1 and ledger[0].entry_type == "manual_topup"
        audits = (await session.scalars(select(AuditLog))).all()
        assert len(audits) == 3
        assert {a.action for a in audits} == {
            "wallet.reconciliation_locked",
            "wallet.cache_repaired",
            "wallet.unlocked",
        }
        repair = next(a for a in audits if a.action == "wallet.cache_repaired")
        assert (
            repair.data["before_balance_vnd"] == 101
            and repair.data["after_balance_vnd"] == 100
        )
        assert (
            repair.permission == "admin.wallet.repair_cache"
            and repair.actor_roles == ["admin"]
        )
        assert len((await session.scalars(select(WalletAudit))).all()) == 1


async def test_missing_invoice_debit_blocks_repair_and_unlock(db_session):
    admin, _ = await setup_wallet(db_session, admin=True)
    wallet, _ = await invoice_wallet(db_session)
    wallet.status = "locked"
    await db_session.flush()
    for command, kwargs in ((mo_khoa_vi, {}), (sua_so_du_cache, {"reason": "Checked"})):
        with pytest.raises(WalletReconciliationError) as error:
            await command(db_session, wallet_id=wallet.id, actor_id=admin.id, **kwargs)
        assert "invoice_debit_count" in error.value.checks
    assert wallet.status == "locked"
    assert await db_session.scalar(select(func.count()).select_from(AuditLog)) == 0


async def test_adjustment_in_locked_wallet_replays_and_never_unlocks(api_db):
    factory, actor, _, wallet_id = api_db
    async with factory() as session, session.begin():
        (await session.get(Wallet, wallet_id)).status = "locked"
    body = {
        "amount_vnd": -50,
        "reason": "Verified correction",
        "audit_id": str(uuid4()),
    }
    first = await request(wallet_id, "adjustments", actor, body)
    assert first.status_code == 201 and first.json()["balance_after_vnd"] == -50
    replay = await request(wallet_id, "adjustments", actor, body)
    assert replay.json() == first.json()
    conflict = await request(
        wallet_id, "adjustments", actor, body | {"amount_vnd": -51}
    )
    assert conflict.status_code == 409
    async with factory() as session:
        wallet = await session.get(Wallet, wallet_id)
        assert wallet.status == "locked"
        entry = await session.get(WalletLedger, first.json()["ledger_id"])
        assert (
            entry.reference_type == "audit" and entry.reference_id == body["audit_id"]
        )
        assert await session.scalar(select(func.count()).select_from(AuditLog)) == 1
        assert await session.scalar(select(func.count()).select_from(WalletAudit)) == 1
    assert (await request(wallet_id, "unlock", actor)).json()["status"] == "active"


@pytest.mark.parametrize("amount", [0, True, 1.5, "1", 2**63, -(2**63) - 1])
async def test_invalid_adjustment_is_rejected(api_db, amount):
    factory, actor, _, wallet_id = api_db
    response = await request(
        wallet_id,
        "adjustments",
        actor,
        {"amount_vnd": amount, "reason": "Checked", "audit_id": str(uuid4())},
    )
    assert response.status_code == 422
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(WalletLedger)) == 0
        assert await session.scalar(select(func.count()).select_from(AuditLog)) == 0


async def test_service_rejects_zero_and_adjustment_does_not_hide_missing_debit(
    db_session,
):
    admin, _ = await setup_wallet(db_session, admin=True)
    wallet, _ = await invoice_wallet(db_session)
    wallet.status = "locked"
    await db_session.flush()
    with pytest.raises(WalletAmountError):
        await dieu_chinh_vi(
            db_session,
            wallet_id=wallet.id,
            actor_id=admin.id,
            amount_vnd=0,
            audit_id=uuid4(),
            reason="Checked",
        )
    await dieu_chinh_vi(
        db_session,
        wallet_id=wallet.id,
        actor_id=admin.id,
        amount_vnd=-200,
        audit_id=uuid4(),
        reason="Correction",
    )
    with pytest.raises(WalletReconciliationError) as error:
        await mo_khoa_vi(db_session, wallet_id=wallet.id, actor_id=admin.id)
    assert "invoice_debit_count" in error.value.checks and wallet.status == "locked"


@pytest.mark.parametrize("command", ["repair", "unlock", "adjust"])
async def test_each_audit_failure_rolls_back_business_changes(
    db_session, monkeypatch, command
):
    admin, wallet = await setup_wallet(db_session, admin=True)
    wallet.status = "locked"
    wallet.balance_vnd = 1 if command == "repair" else 0
    await db_session.flush()
    module = service if command == "repair" else administration
    original = module.ghi_nhat_ky

    async def fail(session, **kwargs):
        await original(session, **kwargs)
        raise RuntimeError("injected audit failure")

    monkeypatch.setattr(module, "ghi_nhat_ky", fail)
    with pytest.raises(RuntimeError):
        kwargs = {"wallet_id": wallet.id, "actor_id": admin.id}
        if command == "repair":
            await sua_so_du_cache(db_session, **kwargs, reason="Checked")
        elif command == "unlock":
            await mo_khoa_vi(db_session, **kwargs)
        else:
            await dieu_chinh_vi(
                db_session, **kwargs, amount_vnd=1, audit_id=uuid4(), reason="Checked"
            )
    await db_session.refresh(wallet)
    assert wallet.status == "locked" and wallet.balance_vnd == (
        1 if command == "repair" else 0
    )
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(AuditLog.actor_id == admin.id)
        )
        == 0
    )
    for model in (WalletAudit, WalletLedger):
        assert (
            await db_session.scalar(
                select(func.count())
                .select_from(model)
                .where(model.wallet_id == wallet.id)
            )
            == 0
        )


async def test_adjustment_key_race_across_wallets_is_safe(isolated_wallet_db):
    factory = isolated_wallet_db
    async with factory() as session:
        admin, first = await setup_wallet(session, admin=True)
        _, second = await setup_wallet(session)
        await session.commit()
    audit_id = uuid4()

    async def adjust(wallet_id):
        async with factory() as session, session.begin():
            try:
                entry = await dieu_chinh_vi(
                    session,
                    wallet_id=wallet_id,
                    actor_id=admin.id,
                    amount_vnd=10,
                    audit_id=audit_id,
                    reason="Checked",
                )
                return entry.id
            except WalletAdjustmentAuditError:
                return None

    results = await asyncio.wait_for(
        asyncio.gather(adjust(first.id), adjust(second.id)), 10
    )
    assert sum(result is not None for result in results) == 1
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(WalletLedger)) == 1
        assert await session.scalar(select(func.count()).select_from(WalletAudit)) == 1
        assert await session.scalar(select(func.count()).select_from(AuditLog)) == 1


async def test_unlock_waits_for_writer_then_rechecks_committed_drift(
    isolated_wallet_db,
):
    factory = isolated_wallet_db
    async with factory() as session:
        admin, wallet = await setup_wallet(session, admin=True)
        wallet.status = "locked"
        await session.commit()
    async with factory() as writer, factory() as unlocker, factory() as observer:
        await writer.execute(
            text("SELECT id FROM wallets WHERE id=:id FOR UPDATE"), {"id": wallet.id}
        )
        await writer.execute(
            text("UPDATE wallets SET balance_vnd=1 WHERE id=:id"), {"id": wallet.id}
        )
        pid = await unlocker.scalar(text("SELECT pg_backend_pid()"))
        task = asyncio.create_task(
            mo_khoa_vi(unlocker, wallet_id=wallet.id, actor_id=admin.id)
        )
        try:
            async with asyncio.timeout(10):
                while not await observer.scalar(
                    text("SELECT cardinality(pg_blocking_pids(:pid)) > 0"), {"pid": pid}
                ):
                    await asyncio.sleep(0.01)
            await writer.commit()
            with pytest.raises(WalletReconciliationError) as error:
                await asyncio.wait_for(task, 10)
            assert error.value.checks == ["balance_mismatch"]
            assert (await unlocker.get(Wallet, wallet.id)).status == "locked"
            assert (
                await unlocker.scalar(select(func.count()).select_from(AuditLog)) == 0
            )
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)


async def test_administrative_actions_follow_caller_rollback(isolated_wallet_db):
    factory = isolated_wallet_db
    async with factory() as session:
        admin, wallet = await setup_wallet(session, admin=True)
        wallet.status = "locked"
        await session.commit()
    async with factory() as writer, factory() as reader:
        await dieu_chinh_vi(
            writer,
            wallet_id=wallet.id,
            actor_id=admin.id,
            amount_vnd=10,
            audit_id=uuid4(),
            reason="Checked",
        )
        await mo_khoa_vi(writer, wallet_id=wallet.id, actor_id=admin.id)
        assert await writer.scalar(select(func.count()).select_from(AuditLog)) == 2
        assert await reader.scalar(select(func.count()).select_from(AuditLog)) == 0
        assert (await reader.get(Wallet, wallet.id)).status == "locked"
        await writer.rollback()
        assert (await writer.get(Wallet, wallet.id)).balance_vnd == 0
        for model in (AuditLog, WalletAudit, WalletLedger):
            assert await writer.scalar(select(func.count()).select_from(model)) == 0


@pytest.mark.parametrize("command", ["repair-cache", "unlock", "adjustments"])
async def test_unknown_wallet_and_inactive_admin(api_db, command):
    factory, actor, _, wallet_id = api_db
    body = (
        {"reason": "Checked", "amount_vnd": 1, "audit_id": str(uuid4())}
        if command == "adjustments"
        else {"reason": "Checked"}
    )
    assert (await request(uuid4(), command, actor, body)).status_code == 404
    from src.modules.identity.models import User

    async with factory() as session, session.begin():
        (await session.get(User, actor.user_id)).status = "deactivated"
    assert (await request(wallet_id, command, actor, body)).status_code == 403
