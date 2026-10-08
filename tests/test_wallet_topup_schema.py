from uuid import uuid4

import pytest
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError

from src.modules.identity.models import User
from src.modules.wallet.topup_models import WalletTopup


async def driver(session):
    user = User(email=f"topup-{uuid4()}@example.com", password_hash="unused")
    session.add(user)
    await session.flush()
    return user


def topup(driver_id, **overrides):
    return WalletTopup(
        **(
            {
                "driver_id": driver_id,
                "amount_vnd": 5_000_000_000,
                "order_id": str(uuid4()),
            }
            | overrides
        )
    )


async def test_pending_defaults_nullable_gateway_and_mutable_status(db_session):
    user = await driver(db_session)
    rows = [topup(user.id), topup(user.id)]
    db_session.add_all(rows)
    await db_session.flush()
    assert all(
        row.status == "pending" and row.gateway_transaction_id is None for row in rows
    )
    assert all(row.created_at.tzinfo and row.updated_at.tzinfo for row in rows)
    assert rows[0].amount_vnd == 5_000_000_000
    rows[0].status = "failed"
    rows[0].reason = "gateway rejected"
    await db_session.flush()
    assert rows[0].reason == "gateway rejected"


@pytest.mark.parametrize(
    "field,constraint",
    [
        ("order_id", "uq_wallet_topups_order"),
        ("gateway_transaction_id", "uq_wallet_topups_gateway"),
    ],
)
async def test_external_ids_unique_across_drivers(db_session, field, constraint):
    first = await driver(db_session)
    second = await driver(db_session)
    identifier = str(uuid4())
    db_session.add(topup(first.id, **{field: identifier}))
    await db_session.flush()
    with pytest.raises(IntegrityError, match=constraint):
        async with db_session.begin_nested():
            db_session.add(topup(second.id, **{field: identifier}))
            await db_session.flush()


@pytest.mark.parametrize(
    "status", ["pending", "succeeded", "failed", "cancelled", "needs_review"]
)
async def test_supported_statuses(db_session, status):
    user = await driver(db_session)
    db_session.add(topup(user.id, status=status))
    await db_session.flush()


@pytest.mark.parametrize(
    "field,value,constraint",
    [
        ("amount_vnd", 0, "ck_wallet_topups_amount"),
        ("amount_vnd", -1, "ck_wallet_topups_amount"),
        ("status", "unknown", "ck_wallet_topups_status"),
        ("order_id", " ", "ck_wallet_topups_order"),
        ("gateway_transaction_id", "", "ck_wallet_topups_gateway"),
    ],
)
async def test_invalid_data_rejected_by_database(db_session, field, value, constraint):
    user = await driver(db_session)
    with pytest.raises(IntegrityError, match=constraint):
        async with db_session.begin_nested():
            db_session.add(topup(user.id, **{field: value}))
            await db_session.flush()


async def test_missing_driver_and_deleting_referenced_driver_rejected(db_session):
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            db_session.add(topup(uuid4()))
            await db_session.flush()
    user = await driver(db_session)
    db_session.add(topup(user.id))
    await db_session.flush()
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await db_session.execute(delete(User).where(User.id == user.id))
