"""T-96 acceptance through HTTP with committed PostgreSQL transactions."""

import asyncio
import hashlib
import hmac
import json
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import func, select, text

from src.config import get_settings
from src.entrypoints.http import app
from src.modules.identity.models import User
from src.modules.payments import webhook_router
from src.modules.wallet import topup_webhook_service as service
from src.modules.wallet.models import Wallet, WalletLedger
from src.modules.wallet.topup_models import WalletTopup
from src.platform.database.session import SessionFactory

SECRET = "t96-isolated-test-secret"
PATH = "/api/v1/payments/webhook"


@pytest_asyncio.fixture
async def context(monkeypatch):
    monkeypatch.setenv("PAYMENT_GATEWAY", "fake")
    monkeypatch.setenv("PAYMENT_WEBHOOK_SECRET", SECRET)
    get_settings.cache_clear()
    orders = []
    async with SessionFactory() as db, db.begin():
        for _ in range(2):
            user = User(email=f"t96-{uuid4()}@example.com", password_hash="unused")
            db.add(user)
            await db.flush()
            wallet = Wallet(driver_id=user.id)
            order = WalletTopup(
                driver_id=user.id, order_id=str(uuid4()), amount_vnd=50000
            )
            db.add_all([wallet, order])
            await db.flush()
            orders.append((order.id, order.order_id, wallet.id))
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://test",
        ) as client:
            yield client, orders
    finally:
        # Keep committed ledger fixtures: production append-only triggers stay enabled.
        get_settings.cache_clear()


def signed(order, tx, status="succeeded", amount=50000):
    body = json.dumps(
        {
            "order_id": order,
            "gateway_transaction_id": tx,
            "amount_vnd": amount,
            "status": status,
            "reason": None,
        },
        separators=(",", ":"),
    ).encode()
    return body, {
        "X-Payment-Signature": "sha256="
        + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
    }


async def post(client, payload):
    body, headers = payload
    return await client.post(PATH, content=body, headers=headers)


async def snapshot(order):
    async with SessionFactory() as db:
        topup = await db.get(WalletTopup, order[0])
        wallet = await db.get(Wallet, order[2])
        ledger = (
            await db.scalars(
                select(WalletLedger).where(WalletLedger.wallet_id == order[2])
            )
        ).all()
        return topup, wallet, ledger


async def test_five_identical_signed_callbacks_are_noop_after_first_commit(context):
    client, orders = context
    order = orders[0]
    tx = str(uuid4())
    payload = signed(order[1], tx)
    first = await post(client, payload)
    assert first.status_code == 200
    before, _, _ = await snapshot(order)
    for _ in range(4):
        replay = await post(client, payload)
        assert replay.status_code == 200 and replay.json() == first.json()
    after, wallet, ledger = await snapshot(order)
    assert after.status == "succeeded" and after.gateway_transaction_id == tx
    assert after.updated_at == before.updated_at
    assert wallet.balance_vnd == 50000 and len(ledger) == 1
    assert ledger[0].reference_id == tx and ledger[0].amount_vnd == 50000


async def test_two_requests_really_wait_on_postgres_order_lock_and_credit_once(
    context, monkeypatch
):
    client, orders = context
    payload = signed(orders[0][1], str(uuid4()))
    credit_flushed, release, second_started = (
        asyncio.Event(),
        asyncio.Event(),
        asyncio.Event(),
    )
    pids = []
    credit_calls = []
    actual_process, actual_credit = (
        webhook_router.process_topup_webhook,
        service.ghi_so_cai,
    )

    async def tracked_process(session, event):
        pids.append(await session.scalar(text("SELECT pg_backend_pid()")))
        if len(pids) == 2:
            second_started.set()
        return await actual_process(session, event)

    async def held_credit(*args, **kwargs):
        credit_calls.append(1)
        result = await actual_credit(*args, **kwargs)
        credit_flushed.set()
        await asyncio.wait_for(release.wait(), 10)
        return result

    monkeypatch.setattr(webhook_router, "process_topup_webhook", tracked_process)
    monkeypatch.setattr(service, "ghi_so_cai", held_credit)
    first = asyncio.create_task(post(client, payload))
    second = None
    try:
        await asyncio.wait_for(credit_flushed.wait(), 5)
        second = asyncio.create_task(post(client, payload))
        await asyncio.wait_for(second_started.wait(), 5)
        assert pids[0] != pids[1]
        async with asyncio.timeout(5):
            while True:
                async with SessionFactory() as observer:
                    blockers = await observer.scalar(
                        text("SELECT pg_blocking_pids(:pid)"), {"pid": pids[1]}
                    )
                if pids[0] in blockers:
                    break
                await asyncio.sleep(0.01)
        assert not second.done()
    finally:
        release.set()
        responses = await asyncio.gather(
            first, *([second] if second is not None else [])
        )
    assert [response.status_code for response in responses] == [200, 200]
    assert (
        responses[0].json()
        == responses[1].json()
        == {"status": "succeeded", "received": True}
    )
    assert len(credit_calls) == 1
    topup, wallet, ledger = await snapshot(orders[0])
    assert (
        topup.status == "succeeded" and wallet.balance_vnd == 50000 and len(ledger) == 1
    )


async def test_concurrent_cross_wallet_reuse_of_gateway_id_has_one_database_winner(
    context, monkeypatch
):
    client, orders = context
    tx = str(uuid4())
    ready = asyncio.Event()
    pids = []
    actual = webhook_router.process_topup_webhook

    async def concurrent(session, event):
        pids.append(await session.scalar(text("SELECT pg_backend_pid()")))
        if len(pids) == 2:
            ready.set()
        await asyncio.wait_for(ready.wait(), 5)
        return await actual(session, event)

    monkeypatch.setattr(webhook_router, "process_topup_webhook", concurrent)
    responses = await asyncio.gather(
        *(post(client, signed(order[1], tx)) for order in orders)
    )
    assert len(set(pids)) == 2
    assert [response.status_code for response in responses] == [200, 200]
    states = [await snapshot(order) for order in orders]
    assert sorted(state[0].status for state in states) == ["needs_review", "succeeded"]
    assert sum(state[1].balance_vnd for state in states) == 50000
    assert sum(len(state[2]) for state in states) == 1
    async with SessionFactory() as db:
        assert (
            await db.scalar(
                select(func.count())
                .select_from(WalletTopup)
                .where(WalletTopup.gateway_transaction_id == tx)
            )
            == 1
        )


async def test_request_failure_before_commit_rolls_back_and_same_callback_can_retry(
    context, monkeypatch
):
    client, orders = context
    payload = signed(orders[0][1], str(uuid4()))
    actual = webhook_router.process_topup_webhook

    async def fail_before_commit(session, event):
        await actual(session, event)
        raise RuntimeError("simulated request failure before commit")

    monkeypatch.setattr(webhook_router, "process_topup_webhook", fail_before_commit)
    assert (await post(client, payload)).status_code == 500
    topup, wallet, ledger = await snapshot(orders[0])
    assert topup.status == "pending" and topup.gateway_transaction_id is None
    assert wallet.balance_vnd == 0 and len(ledger) == 0
    monkeypatch.setattr(webhook_router, "process_topup_webhook", actual)
    for _ in range(2):
        assert (await post(client, payload)).status_code == 200
    topup, wallet, ledger = await snapshot(orders[0])
    assert (
        topup.status == "succeeded" and wallet.balance_vnd == 50000 and len(ledger) == 1
    )


@pytest.mark.parametrize("status", ["failed", "cancelled"])
async def test_repeated_non_success_callbacks_never_credit(context, status):
    client, orders = context
    payload = signed(orders[0][1], str(uuid4()), status=status)
    for _ in range(5):
        assert (await post(client, payload)).status_code == 200
    topup, wallet, ledger = await snapshot(orders[0])
    assert topup.status == status and wallet.balance_vnd == 0 and len(ledger) == 0


async def test_replay_still_authenticates_bytes_and_amount(context):
    client, orders = context
    tx = str(uuid4())
    payload = signed(orders[0][1], tx)
    assert (await post(client, payload)).status_code == 200
    body, headers = payload
    assert (
        await post(client, (body.replace(b"50000", b"60000"), headers))
    ).status_code == 401
    assert (
        await post(client, signed(orders[0][1], tx, amount=60000))
    ).status_code == 400
    topup, wallet, ledger = await snapshot(orders[0])
    assert (
        topup.status == "succeeded" and wallet.balance_vnd == 50000 and len(ledger) == 1
    )
