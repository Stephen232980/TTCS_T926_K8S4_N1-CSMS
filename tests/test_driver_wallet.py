from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from src.entrypoints.http import app
from src.modules.identity.authorization import CurrentActor
from src.modules.identity.dependencies import get_current_actor
from src.modules.identity.models import Role, User, UserRole
from src.modules.identity.security import hash_password
from src.modules.wallet.provisioning import ensure_driver_wallet
from src.modules.wallet.service import ghi_so_cai


@pytest_asyncio.fixture
async def driver_user(db_session):
    role = await db_session.scalar(select(Role).where(Role.code == "driver"))
    if not role:
        role = Role(code="driver")
        db_session.add(role)
        await db_session.commit()
        await db_session.refresh(role)

    user = User(
        email=f"driver-{uuid4().hex[:8]}@example.com",
        password_hash=hash_password("Password123!"),
        status="active",
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    user_role = UserRole(user_id=user.id, role_id=role.id, is_default=True)
    db_session.add(user_role)
    await db_session.commit()
    return user


@pytest_asyncio.fixture
async def operator_user(db_session):
    role = await db_session.scalar(select(Role).where(Role.code == "operator"))
    if not role:
        role = Role(code="operator")
        db_session.add(role)
        await db_session.commit()
        await db_session.refresh(role)

    user = User(
        email=f"operator-{uuid4().hex[:8]}@example.com",
        password_hash=hash_password("Password123!"),
        status="active",
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    user_role = UserRole(user_id=user.id, role_id=role.id, is_default=True)
    db_session.add(user_role)
    await db_session.commit()
    return user


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path", ["/api/v1/driver/wallet", "/api/v1/driver/wallet/transactions"]
)
async def test_wallet_unauthorized_for_anonymous(path):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        res = await client.get(path)
        assert res.status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path", ["/api/v1/driver/wallet", "/api/v1/driver/wallet/transactions"]
)
async def test_wallet_forbidden_for_non_driver(path):
    actor = CurrentActor(user_id=uuid4(), roles=frozenset({"operator"}))
    app.dependency_overrides[get_current_actor] = lambda: actor
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            res = await client.get(path)
            assert res.status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_actor, None)


@pytest.mark.asyncio
async def test_driver_wallet_get_and_cursor_pagination(db_session, driver_user):
    actor = CurrentActor(user_id=driver_user.id, roles=frozenset({"driver"}))
    app.dependency_overrides[get_current_actor] = lambda: actor

    try:
        wallet = await ensure_driver_wallet(db_session, driver_user.id)
        await db_session.commit()

        # Add 3 transactions
        await ghi_so_cai(
            db_session,
            wallet_id=wallet.id,
            entry_type="gateway_topup",
            amount_vnd=100000,
            reference_type="payment",
            reference_id=f"PAY-{uuid4().hex[:8]}",
        )
        await ghi_so_cai(
            db_session,
            wallet_id=wallet.id,
            entry_type="charging_debit",
            amount_vnd=-40000,
            reference_type="charging_session",
            reference_id=f"CS-{uuid4().hex[:8]}",
        )
        await ghi_so_cai(
            db_session,
            wallet_id=wallet.id,
            entry_type="gateway_topup",
            amount_vnd=50000,
            reference_type="payment",
            reference_id=f"PAY-{uuid4().hex[:8]}",
        )
        await db_session.commit()

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            # 1. Get Wallet Balance
            res = await client.get("/api/v1/driver/wallet")
            assert res.status_code == 200
            data = res.json()
            assert data["driver_id"] == str(driver_user.id)
            assert data["balance_vnd"] == "110000"
            assert data["balance"] == "110000"
            assert data["status"] == "active"
            assert data["is_negative"] is False
            assert data["debt_amount_vnd"] == "0"

            # 2. Get Ledger Transactions (limit=2)
            res_tx = await client.get("/api/v1/driver/wallet/transactions?limit=2")
            assert res_tx.status_code == 200
            tx_data = res_tx.json()
            assert len(tx_data["items"]) == 2
            assert tx_data["has_more"] is True
            assert tx_data["next_cursor"] is not None

            # Check sort order: newest first (higher ID first)
            first_id = tx_data["items"][0]["id"]
            second_id = tx_data["items"][1]["id"]
            assert first_id > second_id

            # 3. Next page using cursor
            cursor = tx_data["next_cursor"]
            res_page2 = await client.get(
                f"/api/v1/driver/wallet/transactions?cursor={cursor}&limit=2"
            )
            assert res_page2.status_code == 200
            page2_data = res_page2.json()
            assert len(page2_data["items"]) == 1
            assert page2_data["has_more"] is False
            assert page2_data["next_cursor"] is None
            assert page2_data["items"][0]["id"] < second_id
    finally:
        app.dependency_overrides.pop(get_current_actor, None)


@pytest.mark.asyncio
async def test_driver_wallet_negative_debt_warning(db_session, driver_user):
    actor = CurrentActor(user_id=driver_user.id, roles=frozenset({"driver"}))
    app.dependency_overrides[get_current_actor] = lambda: actor

    try:
        wallet = await ensure_driver_wallet(db_session, driver_user.id)
        # Directly set negative balance to test debt calculation
        wallet.balance_vnd = -75000
        await db_session.commit()

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            res = await client.get("/api/v1/driver/wallet")
            assert res.status_code == 200
            data = res.json()
            assert data["balance_vnd"] == "-75000"
            assert data["balance"] == "-75000"
            assert data["is_negative"] is True
            assert data["debt_amount_vnd"] == "75000"
            assert data["debt_amount"] == "75000"
    finally:
        app.dependency_overrides.pop(get_current_actor, None)


@pytest.mark.asyncio
async def test_two_drivers_have_separate_balances_and_transactions(
    db_session, driver_user
):
    other = User(
        email=f"other-{uuid4().hex}@example.com",
        password_hash=hash_password("Password123!"),
        status="active",
    )
    db_session.add(other)
    await db_session.flush()
    role = await db_session.scalar(select(Role).where(Role.code == "driver"))
    db_session.add(UserRole(user_id=other.id, role_id=role.id, is_default=True))
    expected = {}
    for user, amount in [(driver_user, 120000), (other, 90000)]:
        wallet = await ensure_driver_wallet(db_session, user.id)
        await db_session.commit()
        reference = f"PAY-{uuid4().hex}"
        await ghi_so_cai(
            db_session,
            wallet_id=wallet.id,
            entry_type="gateway_topup",
            amount_vnd=amount,
            reference_type="payment",
            reference_id=reference,
        )
        expected[user.id] = (amount, reference)
    await db_session.commit()
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            for user in [driver_user, other]:
                actor = CurrentActor(user_id=user.id, roles=frozenset({"driver"}))
                app.dependency_overrides[get_current_actor] = lambda actor=actor: actor
                balance = await client.get("/api/v1/driver/wallet")
                ledger = await client.get("/api/v1/driver/wallet/transactions")
                assert balance.status_code == ledger.status_code == 200
                assert balance.json()["balance_vnd"] == str(expected[user.id][0])
                assert [item["reference_id"] for item in ledger.json()["items"]] == [
                    expected[user.id][1]
                ]
    finally:
        app.dependency_overrides.pop(get_current_actor, None)


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["", "/transactions"])
@pytest.mark.parametrize("selector", ["driver_id", "wallet_id"])
async def test_wallet_rejects_selectors(db_session, driver_user, path, selector):
    app.dependency_overrides[get_current_actor] = lambda: CurrentActor(
        user_id=driver_user.id, roles=frozenset({"driver"})
    )
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            assert (
                await client.get(f"/api/v1/driver/wallet{path}?{selector}={uuid4()}")
            ).status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_actor, None)


@pytest.mark.asyncio
async def test_wallet_default_50_pages_with_new_insert(db_session, driver_user):
    from src.modules.wallet.models import WalletLedger

    wallet = await ensure_driver_wallet(db_session, driver_user.id)
    for _ in range(120):
        await ghi_so_cai(
            db_session,
            wallet_id=wallet.id,
            entry_type="gateway_topup",
            amount_vnd=1,
            reference_type="payment",
            reference_id=str(uuid4()),
        )
    await db_session.commit()
    original = set(
        await db_session.scalars(
            select(WalletLedger.id).where(WalletLedger.wallet_id == wallet.id)
        )
    )
    app.dependency_overrides[get_current_actor] = lambda: CurrentActor(
        user_id=driver_user.id, roles=frozenset({"driver"})
    )
    try:
        seen = []
        sizes = []
        cursor = None
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            for index in range(3):
                r = await client.get(
                    "/api/v1/driver/wallet/transactions",
                    params={"cursor": cursor} if cursor else {},
                )
                assert r.status_code == 200
                data = r.json()
                sizes.append(len(data["items"]))
                seen.extend(row["id"] for row in data["items"])
                cursor = data["next_cursor"]
                if index == 0:
                    await ghi_so_cai(
                        db_session,
                        wallet_id=wallet.id,
                        entry_type="gateway_topup",
                        amount_vnd=1,
                        reference_type="payment",
                        reference_id=str(uuid4()),
                    )
                    await db_session.commit()
        assert (
            sizes == [50, 50, 20]
            and len(seen) == len(set(seen)) == 120
            and set(seen) == original
        )
    finally:
        app.dependency_overrides.pop(get_current_actor, None)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["gateway", "manual", "legacy"])
async def test_wallet_transaction_ownership_topup_and_exact_money(
    db_session, driver_user, kind
):
    from src.modules.wallet.models import WalletLedger
    from src.modules.wallet.topup_models import WalletTopup

    wallet = await ensure_driver_wallet(db_session, driver_user.id)
    amount = 9007199254740993
    gateway_id = "qa-" + uuid4().hex
    entry = await ghi_so_cai(
        db_session,
        wallet_id=wallet.id,
        entry_type="manual_topup" if kind == "manual" else "gateway_topup",
        amount_vnd=amount,
        reference_type="manual_topup" if kind == "manual" else "gateway_transaction",
        actor_id=driver_user.id if kind == "manual" else None,
        reference_id=gateway_id,
    )
    order = "order-" + uuid4().hex
    if kind == "gateway":
        db_session.add(
            WalletTopup(
                driver_id=driver_user.id,
                amount_vnd=amount,
                order_id=order,
                status="succeeded",
                gateway_transaction_id=gateway_id,
            )
        )
    await db_session.commit()
    app.dependency_overrides[get_current_actor] = lambda: CurrentActor(
        user_id=driver_user.id, roles=frozenset({"driver"})
    )
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get(
                f"/api/v1/driver/wallet/transactions/{entry.id}"
            )
            assert response.status_code == 200
            data = response.json()
            assert data["amount_vnd"] == data["balance_after_vnd"] == str(amount)
            if kind == "gateway":
                assert (
                    data["topup_order_id"] == order
                    and data["topup_status"] == "succeeded"
                )
            else:
                assert data["topup_order_id"] is None and data["topup_status"] is None
            balance = (await client.get("/api/v1/driver/wallet")).json()
            assert balance["balance"] == balance["balance_vnd"] == str(amount)
            app.dependency_overrides[get_current_actor] = lambda: CurrentActor(
                user_id=uuid4(), roles=frozenset({"driver"})
            )
            assert (
                await client.get(f"/api/v1/driver/wallet/transactions/{entry.id}")
            ).status_code == 403
            assert (
                await client.get("/api/v1/driver/wallet/transactions/2147483647")
            ).status_code == 404
            assert (
                await db_session.scalar(
                    select(WalletLedger.amount_vnd).where(WalletLedger.id == entry.id)
                )
                == amount
            )
    finally:
        app.dependency_overrides.pop(get_current_actor, None)
