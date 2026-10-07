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
async def test_wallet_unauthorized_for_anonymous():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        res = await client.get("/api/v1/driver/wallet")
        assert res.status_code == 401


@pytest.mark.asyncio
async def test_wallet_forbidden_for_non_driver(operator_user):
    actor = CurrentActor(
        user_id=operator_user.id, roles=frozenset({"operator"})
    )
    app.dependency_overrides[get_current_actor] = lambda: actor
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            res = await client.get("/api/v1/driver/wallet")
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
            assert data["balance_vnd"] == 110000
            assert data["balance"] == 110000
            assert data["status"] == "active"
            assert data["is_negative"] is False
            assert data["debt_amount_vnd"] == 0

            # 2. Get Ledger Transactions (limit=2)
            res_tx = await client.get(
                "/api/v1/driver/wallet/transactions?limit=2"
            )
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
            assert data["balance_vnd"] == -75000
            assert data["balance"] == -75000
            assert data["is_negative"] is True
            assert data["debt_amount_vnd"] == 75000
            assert data["debt_amount"] == 75000
    finally:
        app.dependency_overrides.pop(get_current_actor, None)
