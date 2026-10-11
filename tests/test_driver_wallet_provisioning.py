import asyncio
import importlib
import os
import subprocess
import sys
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import func, select, text

from scripts import create_test_accounts
from src.modules.charging.driver import virtual_tag
from src.modules.charging.driver_models import DriverVirtualTag
from src.modules.charging.models import ChargingCard
from src.modules.identity import role_assignment
from src.modules.identity.admin_schemas import AccountCreateRequest
from src.modules.identity.admin_service import AdminAccountService
from src.modules.identity.authorization import CurrentActor
from src.modules.identity.models import Role, User, UserRole
from src.modules.identity.role_assignment import assign_user_roles
from src.modules.wallet.models import Wallet, WalletLedger
from src.modules.wallet.provisioning import (
    WalletDriverRequiredError,
    ensure_driver_wallet,
)
from src.modules.wallet.service import ghi_so_cai
from tests.test_effective_tariffs import committed_tariff_db as tariff_database
from tests.test_ocpp_control import db_session as control_database

db_session = control_database
committed_driver_db = tariff_database


async def test_seed_twice_creates_wallet_and_tag_without_orphan_accounts(
    db_session, monkeypatch
):
    class Factory:
        def __call__(self):
            return db_session

    email = f"seed-{uuid4()}@example.com"
    monkeypatch.setattr(create_test_accounts, "SessionFactory", Factory())
    monkeypatch.setattr(
        create_test_accounts,
        "accounts",
        [{"email": email, "password": "Test-only-2026!", "role": "driver"}],
    )
    await db_session.commit()
    await create_test_accounts.main()
    await create_test_accounts.main()
    account = await db_session.scalar(select(User).where(User.email == email))
    wallet = await ensure_driver_wallet(db_session, account.id)
    assert wallet.balance_vnd == 0
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(DriverVirtualTag)
            .where(DriverVirtualTag.driver_id == account.id)
        )
        == 1
    )


async def test_seed_failure_rolls_back_new_driver(db_session, monkeypatch):
    email = f"seed-failed-{uuid4()}@example.com"
    original = role_assignment.ensure_driver_resources

    async def fail(session, driver):
        await original(session, driver)
        raise RuntimeError("Seed provisioning failed")

    monkeypatch.setattr(role_assignment, "ensure_driver_resources", fail)
    monkeypatch.setattr(create_test_accounts, "SessionFactory", lambda: db_session)
    monkeypatch.setattr(
        create_test_accounts,
        "accounts",
        [{"email": email, "password": "Test-only-2026!", "role": "driver"}],
    )
    await db_session.commit()
    with pytest.raises(RuntimeError, match="Seed provisioning failed"):
        await create_test_accounts.main()
    assert await db_session.scalar(select(User.id).where(User.email == email)) is None


async def test_migration_upgrade_and_downgrade_keep_funded_wallet(committed_driver_db):
    factory = committed_driver_db
    url = factory.kw["bind"].url.render_as_string(hide_password=False)
    async with factory() as session:
        legacy = await user(session, ["driver"])
        funded = await user(session, ["driver"])
        wallet = await ensure_driver_wallet(session, funded.id)
        await ghi_so_cai(
            session,
            wallet_id=wallet.id,
            entry_type="manual_topup",
            amount_vnd=5000,
            reference_type="test",
            reference_id=str(uuid4()),
        )
        await session.commit()
    for direction, revision in [
        ("downgrade", "c100011a2026"),
        ("upgrade", "head"),
        ("downgrade", "c100011a2026"),
        ("upgrade", "head"),
    ]:
        await asyncio.to_thread(
            subprocess.run,
            [sys.executable, "-m", "alembic", direction, revision],
            env=os.environ | {"DATABASE_URL": url},
            check=True,
            capture_output=True,
        )
    async with factory() as session:
        assert (await ensure_driver_wallet(session, legacy.id)).balance_vnd == 0
        assert (await session.get(Wallet, wallet.id)).balance_vnd == 5000
        assert (
            await session.scalar(
                select(func.count())
                .select_from(WalletLedger)
                .where(WalletLedger.wallet_id == wallet.id)
            )
            == 1
        )


async def user(session, roles=()):
    account = User(email=f"t85-{uuid4()}@example.com", password_hash="unused")
    session.add(account)
    await session.flush()
    for code in roles:
        role = await session.scalar(select(Role).where(Role.code == code))
        session.add(UserRole(user_id=account.id, role_id=role.id))
    await session.flush()
    return account


@pytest.mark.parametrize(
    "roles", [["driver"], ["driver", "station_owner"], ["operator"]]
)
async def test_admin_create_provisions_driver_in_account_transaction(db_session, roles):
    admin = await user(db_session, ["admin"])
    email = f"created-{uuid4()}@example.com"
    result = await AdminAccountService(db_session).create(
        AccountCreateRequest(email=email, password="Test-only-2026!", roles=roles),
        CurrentActor(user_id=admin.id, roles=frozenset({"admin"})),
    )
    wallets = (
        await db_session.scalars(select(Wallet).where(Wallet.driver_id == result.id))
    ).all()
    tag = await db_session.get(DriverVirtualTag, result.id)
    if "driver" in roles:
        assert len(wallets) == 1 and wallets[0].balance_vnd == 0
        assert (
            tag is not None
            and await db_session.get(ChargingCard, tag.card_id) is not None
        )
        assert (
            await db_session.scalar(
                select(func.count())
                .select_from(WalletLedger)
                .where(WalletLedger.wallet_id == wallets[0].id)
            )
            == 0
        )
    else:
        assert not wallets and tag is None


async def test_provisioning_failure_rolls_back_account_role_wallet_tag_and_card(
    db_session, monkeypatch
):
    admin = await user(db_session, ["admin"])
    original = role_assignment.ensure_driver_resources
    captured = {}

    async def fail_after_provision(session, driver):
        tag = await original(session, driver)
        captured.update(driver=driver.id, card=tag.card_id)
        raise RuntimeError("Provisioning failed")

    monkeypatch.setattr(
        role_assignment, "ensure_driver_resources", fail_after_provision
    )
    email = f"failed-{uuid4()}@example.com"
    with pytest.raises(RuntimeError, match="Provisioning failed"):
        await AdminAccountService(db_session).create(
            AccountCreateRequest(
                email=email, password="Test-only-2026!", roles=["driver"]
            ),
            CurrentActor(user_id=admin.id, roles=frozenset({"admin"})),
        )
    assert await db_session.get(User, captured["driver"]) is None
    assert await db_session.get(ChargingCard, captured["card"]) is None
    assert await db_session.get(DriverVirtualTag, captured["driver"]) is None
    assert (
        await db_session.scalar(
            select(Wallet.id).where(Wallet.driver_id == captured["driver"])
        )
        is None
    )
    assert (
        await db_session.scalar(
            select(UserRole.user_id).where(UserRole.user_id == captured["driver"])
        )
        is None
    )


async def test_role_add_remove_readd_and_repeat_preserve_wallet_and_tag(db_session):
    account = await user(db_session)
    await assign_user_roles(db_session, account.id, ["station_owner"])
    assert (
        await db_session.scalar(select(Wallet.id).where(Wallet.driver_id == account.id))
        is None
    )
    await assign_user_roles(db_session, account.id, ["driver"], replace=False)
    wallet = await ensure_driver_wallet(db_session, account.id)
    tag = await db_session.get(DriverVirtualTag, account.id)
    tag_id = tag.id_tag
    await ghi_so_cai(
        db_session,
        wallet_id=wallet.id,
        entry_type="manual_topup",
        amount_vnd=5000,
        reference_type="test",
        reference_id=str(uuid4()),
    )
    wallet.status = "locked"
    await db_session.flush()
    await assign_user_roles(db_session, account.id, ["station_owner"])
    await assign_user_roles(db_session, account.id, ["driver"], replace=False)
    for _ in range(5):
        restored = await ensure_driver_wallet(db_session, account.id)
        await assign_user_roles(db_session, account.id, ["driver", "station_owner"])
        assert (
            restored.id == wallet.id
            and restored.balance_vnd == 5000
            and restored.status == "locked"
        )
        assert (await db_session.get(DriverVirtualTag, account.id)).id_tag == tag_id


async def test_non_driver_and_missing_user_cannot_provision(db_session):
    account = await user(db_session, ["operator"])
    for driver_id in [account.id, uuid4()]:
        with pytest.raises(WalletDriverRequiredError):
            await ensure_driver_wallet(db_session, driver_id)


async def test_legacy_virtual_tag_path_creates_missing_wallet_once(db_session):
    driver = await user(db_session, ["driver"])
    first = await virtual_tag(db_session, driver)
    assert await virtual_tag(db_session, driver) == first
    wallet = await ensure_driver_wallet(db_session, driver.id)
    assert wallet.balance_vnd == 0
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(Wallet)
            .where(Wallet.driver_id == driver.id)
        )
        == 1
    )


async def test_blocked_virtual_card_is_not_replaced_or_reactivated(db_session):
    driver = await user(db_session)
    await assign_user_roles(db_session, driver.id, ["driver"])
    tag = await db_session.get(DriverVirtualTag, driver.id)
    card = await db_session.get(ChargingCard, tag.card_id)
    card.status = "blocked"
    await db_session.flush()
    await assign_user_roles(db_session, driver.id, ["driver"])
    assert (await db_session.get(DriverVirtualTag, driver.id)).card_id == card.id
    assert card.status == "blocked"


async def test_backfill_twice_preserves_existing_money_and_skips_non_drivers(
    db_session, monkeypatch
):
    legacy = await user(db_session, ["driver", "station_owner"])
    suspended = await user(db_session, ["driver"])
    suspended.status = "suspended"
    non_driver = await user(db_session, ["operator"])
    funded = await user(db_session, ["driver"])
    wallet = await ensure_driver_wallet(db_session, funded.id)
    await ghi_so_cai(
        db_session,
        wallet_id=wallet.id,
        entry_type="manual_topup",
        amount_vnd=1000,
        reference_type="test",
        reference_id=str(uuid4()),
    )
    wallet.status = "locked"
    await db_session.flush()
    migration = importlib.import_module(
        "migrations.versions.d110012a2026_backfill_driver_wallets"
    )
    connection = await db_session.connection()

    def run(connection):
        monkeypatch.setattr(
            migration, "op", Operations(MigrationContext.configure(connection))
        )
        migration.upgrade()
        migration.upgrade()
        migration.downgrade()

    await connection.run_sync(run)
    for account in [legacy, suspended]:
        result = (
            await db_session.scalars(
                select(Wallet).where(Wallet.driver_id == account.id)
            )
        ).all()
        assert len(result) == 1 and result[0].balance_vnd == 0
    assert (
        await db_session.scalar(
            select(Wallet.id).where(Wallet.driver_id == non_driver.id)
        )
        is None
    )
    await db_session.refresh(wallet)
    assert wallet.balance_vnd == 1000 and wallet.status == "locked"
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(WalletLedger)
            .where(WalletLedger.wallet_id == wallet.id)
        )
        == 1
    )


async def test_concurrent_provisioning_is_one_wallet_and_one_tag(committed_driver_db):
    factory = committed_driver_db
    async with factory() as setup:
        driver = await user(setup, ["driver"])
        await setup.commit()
    ready = asyncio.Barrier(2)

    async def provision():
        async with factory() as session:
            pid = await session.scalar(text("SELECT pg_backend_pid()"))
            await ready.wait()
            account = await session.get(User, driver.id)
            result = await virtual_tag(session, account)
            wallet = await ensure_driver_wallet(session, account.id)
            await session.commit()
            return pid, wallet.id, result

    results = await asyncio.wait_for(asyncio.gather(provision(), provision()), 20)
    assert results[0][0] != results[1][0]
    assert results[0][1:] == results[1][1:]
    async with factory() as session:
        assert (
            await session.scalar(
                select(func.count())
                .select_from(Wallet)
                .where(Wallet.driver_id == driver.id)
            )
            == 1
        )
        assert (
            await session.scalar(
                select(func.count())
                .select_from(ChargingCard)
                .where(ChargingCard.driver_id == driver.id)
            )
            == 1
        )
