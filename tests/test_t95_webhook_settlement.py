import hashlib
import hmac
import json
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import func, select

from src.config import get_settings
from src.entrypoints.http import app
from src.modules.identity.models import User
from src.modules.wallet.models import Wallet, WalletLedger
from src.modules.wallet.topup_models import WalletTopup
from src.modules.wallet.topup_webhook_service import TRANSITIONS
from src.platform.database.session import SessionFactory

SECRET = "t95-test-secret"
PATH = "/api/v1/payments/webhook"


@pytest_asyncio.fixture
async def context(monkeypatch):
    monkeypatch.setenv("PAYMENT_GATEWAY", "fake")
    monkeypatch.setenv("PAYMENT_WEBHOOK_SECRET", SECRET)
    get_settings.cache_clear()
    async with SessionFactory() as db, db.begin():
        user = User(email=f"t95-{uuid4()}@example.com", password_hash="unused")
        db.add(user)
        await db.flush()
        wallet = Wallet(driver_id=user.id)
        topup = WalletTopup(driver_id=user.id, order_id=str(uuid4()), amount_vnd=50000)
        db.add_all([wallet, topup])
        await db.flush()
        ids = user.id, wallet.id, topup.id, topup.order_id
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield client, ids
    finally:
        get_settings.cache_clear()


async def send(client, order, status="succeeded", amount=50000, tx=None, reason=None):
    body = json.dumps(
        {
            "order_id": order,
            "amount_vnd": amount,
            "gateway_transaction_id": tx or str(uuid4()),
            "status": status,
            "reason": reason,
        }
    ).encode()
    signature = "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
    return await client.post(
        PATH, content=body, headers={"X-Payment-Signature": signature}
    )


async def read(ids):
    async with SessionFactory() as db:
        topup = await db.get(WalletTopup, ids[2])
        wallet = await db.get(Wallet, ids[1])
        count = await db.scalar(
            select(func.count())
            .select_from(WalletLedger)
            .where(WalletLedger.wallet_id == ids[1])
        )
        return topup, wallet, count


@pytest.mark.parametrize(
    "old,event", [(old, event) for old in TRANSITIONS for event in TRANSITIONS[old]]
)
async def test_state_matrix(context, old, event):
    client, ids = context
    tx = str(uuid4())
    async with SessionFactory() as db, db.begin():
        topup = await db.get(WalletTopup, ids[2])
        topup.status = old
        if old != "pending":
            topup.gateway_transaction_id = tx
    response = await send(
        client, ids[3], status=event, tx=tx, reason="gateway declined"
    )
    assert response.status_code == 200
    topup, wallet, count = await read(ids)
    assert topup.status == TRANSITIONS[old][event]
    credit = old == "pending" and event == "succeeded"
    assert wallet.balance_vnd == (50000 if credit else 0)
    assert count == int(credit)
    if old == "pending" and event != "succeeded":
        assert topup.reason == "gateway declined"


async def test_amount_mismatch_commits_review_and_no_credit(context):
    client, ids = context
    response = await send(client, ids[3], amount=49999)
    assert response.status_code == 400
    topup, wallet, count = await read(ids)
    assert topup.status == "needs_review" and wallet.balance_vnd == 0 and count == 0


async def test_signature_verified_before_json_and_no_side_effect(context, caplog):
    client, ids = context
    for headers in [{}, {"X-Payment-Signature": "sha256=" + "0" * 64}]:
        response = await client.post(
            PATH, content=b"private invalid json", headers=headers
        )
        assert response.status_code == 401
    topup, wallet, count = await read(ids)
    assert topup.status == "pending" and wallet.balance_vnd == 0 and count == 0
    assert "private invalid json" not in caplog.text and SECRET not in caplog.text
    assert "client_ip" in caplog.text


async def test_unknown_order_and_authenticated_invalid_json(context):
    client, _ids = context
    assert (await send(client, str(uuid4()))).status_code == 404
    body = b"invalid json"
    sig = "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
    assert (
        await client.post(PATH, content=body, headers={"X-Payment-Signature": sig})
    ).status_code == 400


async def test_real_ledger_conflict_marks_review_without_500(context):
    client, ids = context
    tx = str(uuid4())
    async with SessionFactory() as db, db.begin():
        db.add(
            WalletLedger(
                wallet_id=ids[1],
                entry_type="gateway_topup",
                amount_vnd=10000,
                balance_after_vnd=10000,
                reference_type="gateway_transaction",
                reference_id=tx,
            )
        )
        wallet = await db.get(Wallet, ids[1])
        wallet.balance_vnd = 10000
    assert (await send(client, ids[3], tx=tx)).status_code == 200
    topup, wallet, count = await read(ids)
    assert topup.status == "needs_review" and wallet.balance_vnd == 10000 and count == 1
    assert topup.gateway_transaction_id is None


async def test_credit_then_failure_rolls_back_savepoint(context, monkeypatch):
    from src.modules.wallet import topup_webhook_service as service
    from src.modules.wallet.exceptions import WalletLedgerConflictError

    actual = service.ghi_so_cai

    async def fail_after_credit(*args, **kwargs):
        await actual(*args, **kwargs)
        raise WalletLedgerConflictError("test conflict after flush")

    monkeypatch.setattr(service, "ghi_so_cai", fail_after_credit)
    client, ids = context
    assert (await send(client, ids[3])).status_code == 200
    topup, wallet, count = await read(ids)
    assert topup.status == "needs_review" and wallet.balance_vnd == 0 and count == 0


async def test_success_is_durable_and_replay_never_downgrades(context):
    client, ids = context
    tx = str(uuid4())
    assert (await send(client, ids[3], tx=tx)).status_code == 200
    assert (await send(client, ids[3], tx=tx)).status_code == 200
    assert (await send(client, ids[3], tx=tx, status="failed")).status_code == 200
    topup, wallet, count = await read(ids)
    assert topup.status == "succeeded" and wallet.balance_vnd == 50000 and count == 1
    async with SessionFactory() as db:
        ledger = await db.scalar(
            select(WalletLedger).where(WalletLedger.wallet_id == ids[1])
        )
        assert ledger.entry_type == "gateway_topup"
        assert (
            ledger.reference_type == "gateway_transaction" and ledger.reference_id == tx
        )


async def test_gateway_transaction_unique_conflict_rolls_back_and_marks_review(context):
    client, ids = context
    tx = str(uuid4())
    async with SessionFactory() as db, db.begin():
        db.add(
            WalletTopup(
                driver_id=ids[0],
                order_id=str(uuid4()),
                amount_vnd=50000,
                status="failed",
                gateway_transaction_id=tx,
            )
        )
    assert (await send(client, ids[3], tx=tx)).status_code == 200
    topup, wallet, count = await read(ids)
    assert topup.status == "needs_review" and topup.gateway_transaction_id is None
    assert wallet.balance_vnd == 0 and count == 0


@pytest.mark.parametrize("balance,locked", [(0, True), (2**63 - 1, False)])
async def test_locked_or_overflow_wallet_does_not_credit(context, balance, locked):
    client, ids = context
    async with SessionFactory() as db, db.begin():
        wallet = await db.get(Wallet, ids[1])
        wallet.balance_vnd = balance
        wallet.status = "locked" if locked else "active"
    assert (await send(client, ids[3])).status_code == 200
    topup, wallet, count = await read(ids)
    assert (
        topup.status == "needs_review" and wallet.balance_vnd == balance and count == 0
    )


async def test_disabled_gateway_does_not_settle_with_existing_secret(
    context, monkeypatch
):
    client, ids = context
    monkeypatch.setenv("PAYMENT_GATEWAY", "disabled")
    get_settings.cache_clear()
    assert (await send(client, ids[3])).status_code == 503
    topup, wallet, count = await read(ids)
    assert topup.status == "pending" and wallet.balance_vnd == 0 and count == 0
