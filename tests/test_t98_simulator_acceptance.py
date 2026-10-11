"""T-98: signed T-93 link -> real T-92 dispatch -> T-95/96/97 -> status and DB.

No dependency, gateway, settlement or ledger mocks. HTTP runs in-process;
PostgreSQL commits, authentication and all business handlers are real.
"""

import asyncio
import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from time import perf_counter
from urllib.parse import parse_qs, urlsplit
from uuid import UUID, uuid4

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from src.config import get_settings
from src.entrypoints.http import app
from src.modules.identity.models import Role, Session, User, UserRole
from src.modules.identity.security import hash_session_token
from src.modules.payments import fake_gateway
from src.modules.payments.contracts import SIGNATURE_HEADER
from src.modules.wallet.models import Wallet, WalletLedger
from src.modules.wallet.topup_models import WalletTopup
from src.platform.audit.models import AuditLog
from src.platform.database.session import SessionFactory

SECRET = "t98-real-simulator-test-secret"
AMOUNT = 100000
WEBHOOK = "/api/v1/payments/webhook"
TOPUPS = "/api/v1/driver/wallet/topups"
DISPATCH = "/api/v1/payments/fake/dispatch"


@dataclass
class Context:
    client: httpx.AsyncClient
    wallet_id: UUID
    topup_id: UUID
    order_id: str
    action: dict[str, str | int]


@pytest_asyncio.fixture
async def context(monkeypatch):
    monkeypatch.setenv("PAYMENT_GATEWAY", "fake")
    monkeypatch.setenv("PAYMENT_WEBHOOK_SECRET", SECRET)
    monkeypatch.setenv("PAYMENT_FAKE_BASE_URL", "http://localhost:8012")
    get_settings.cache_clear()
    token = uuid4().hex
    async with SessionFactory() as db, db.begin():
        role = await db.scalar(select(Role).where(Role.code == "driver"))
        assert role is not None
        driver = User(email=f"t98-flow-{uuid4()}@example.com", password_hash="unused")
        db.add(driver)
        await db.flush()
        db.add(UserRole(user_id=driver.id, role_id=role.id))
        db.add(
            Session(
                user_id=driver.id,
                token_hash=hash_session_token(token),
                expires_at=datetime.now(UTC) + timedelta(hours=1),
            )
        )
        driver_id = driver.id
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://localhost:8012",
            cookies={"session": token},
        ) as client:
            created = await client.post(TOPUPS, json={"amount_vnd": AMOUNT})
            assert created.status_code == 201, created.text
            data = created.json()
            assert data["status"] == "pending" and data["amount_vnd"] == AMOUNT
            action = {
                key: values[0]
                for key, values in parse_qs(
                    urlsplit(data["redirect_url"]).query
                ).items()
            }
            action["amount_vnd"] = int(action["amount_vnd"])
            action["expires"] = int(action["expires"])
            page = await client.get(data["redirect_url"])
            assert page.status_code == 200
            assert SECRET not in page.text
            async with SessionFactory() as db:
                wallet = await db.scalar(
                    select(Wallet).where(Wallet.driver_id == driver_id)
                )
                topup = await db.scalar(
                    select(WalletTopup).where(WalletTopup.order_id == data["order_id"])
                )
                assert wallet is not None and topup is not None
                assert wallet.balance_vnd == 0 and topup.status == "pending"
                assert topup.driver_id == driver_id
            yield Context(client, wallet.id, topup.id, topup.order_id, action)
    finally:
        # Preserve append-only financial/audit evidence in the disposable DB.
        get_settings.cache_clear()


async def snapshot(context):
    async with SessionFactory() as db:
        topup = await db.get(WalletTopup, context.topup_id)
        wallet = await db.get(Wallet, context.wallet_id)
        entries = list(
            await db.scalars(
                select(WalletLedger)
                .where(WalletLedger.wallet_id == context.wallet_id)
                .order_by(WalletLedger.id)
            )
        )
        assert topup is not None and wallet is not None
        return {
            "status": topup.status,
            "reason": topup.reason,
            "tx": topup.gateway_transaction_id,
            "updated_at": topup.updated_at,
            "balance": wallet.balance_vnd,
            "wallet_status": wallet.status,
            "ledger": [
                (
                    e.id,
                    e.entry_type,
                    e.amount_vnd,
                    e.balance_after_vnd,
                    e.reference_type,
                    e.reference_id,
                )
                for e in entries
            ],
        }


async def assert_state(context, status, balance, count, tx=None):
    state = await snapshot(context)
    assert state["status"] == status and state["balance"] == balance
    assert state["wallet_status"] == "active" and len(state["ledger"]) == count
    if count:
        assert state["ledger"][0][1:5] == (
            "gateway_topup",
            AMOUNT,
            AMOUNT,
            "gateway_transaction",
        )
        assert state["ledger"][0][5] == state["tx"]
    if tx is not None:
        assert state["tx"] == tx
    # Public status read used by T-94 agrees with independently committed DB state.
    order = await context.client.get(f"{TOPUPS}/{context.order_id}")
    wallet = await context.client.get("/api/v1/driver/wallet")
    ledger = await context.client.get("/api/v1/driver/wallet/transactions")
    assert order.status_code == wallet.status_code == ledger.status_code == 200
    assert order.json()["status"] == status and order.json()["amount_vnd"] == AMOUNT
    assert wallet.json()["balance_vnd"] == balance
    assert len(ledger.json()["items"]) == count
    return state


async def warnings_for(context):
    async with SessionFactory() as db:
        return list(
            await db.scalars(
                select(AuditLog).where(
                    AuditLog.object_type == "wallet_topup",
                    AuditLog.object_id == str(context.topup_id),
                    AuditLog.action.like("payment_webhook.%"),
                )
            )
        )


def signed(context, **changes):
    data = {
        "order_id": context.order_id,
        "amount_vnd": AMOUNT,
        "status": "succeeded",
        "gateway_transaction_id": f"t98-tx-{context.topup_id}",
        "reason": "Lý do riêng UTF-8",
    }
    data.update(changes)
    body = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode()
    signature = "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
    return body, signature


async def callback(context, **changes):
    body, signature = signed(context, **changes)
    return await context.client.post(
        WEBHOOK, content=body, headers={SIGNATURE_HEADER: signature}
    )


async def dispatch(context, status="succeeded", **options):
    return await context.client.post(
        DISPATCH, json={**context.action, "status": status, **options}
    )


@pytest.mark.parametrize("status", ["succeeded", "failed", "cancelled"])
async def test_signed_simulator_link_settles_and_replays_with_one_gateway_id(
    context, status
):
    await assert_state(context, "pending", 0, 0)
    first = await dispatch(
        context, status, repeat_count=5, reason="Kết quả mô phỏng UTF-8"
    )
    assert first.status_code == 200
    assert first.json()["statuses"] == [200] * 5
    tx = first.json()["gateway_transaction_id"]
    assert tx == "fake-tx-" + hashlib.sha256(context.order_id.encode()).hexdigest()[:32]
    credit = status == "succeeded"
    settled = await assert_state(
        context, status, AMOUNT if credit else 0, int(credit), tx
    )
    second = await dispatch(
        context, status, repeat_count=5, reason="Kết quả mô phỏng UTF-8"
    )
    assert second.status_code == 200 and second.json()["statuses"] == [200] * 5
    assert second.json()["gateway_transaction_id"] == tx
    assert await snapshot(context) == settled
    assert await warnings_for(context) == []
    assert "signature" not in first.text and SECRET not in first.text


@pytest.mark.parametrize(
    "initial,event,final,code,balance,count",
    [
        ("succeeded", "failed", "succeeded", "late_non_success", AMOUNT, 1),
        ("succeeded", "cancelled", "succeeded", "late_non_success", AMOUNT, 1),
        ("failed", "succeeded", "needs_review", "late_success", 0, 0),
        ("cancelled", "succeeded", "needs_review", "late_success", 0, 0),
    ],
)
async def test_simulator_out_of_order_callbacks_match_t97_contract(
    context, caplog, initial, event, final, code, balance, count
):
    first = await dispatch(context, initial)
    assert first.status_code == 200
    tx = first.json()["gateway_transaction_id"]
    before = await snapshot(context)
    second = await dispatch(
        context, event, repeat_count=5, reason="PRIVATE_GATEWAY_REASON"
    )
    assert second.status_code == 200 and second.json()["statuses"] == [200] * 5
    assert second.json()["gateway_transaction_id"] == tx
    after = await assert_state(context, final, balance, count, tx)
    assert after["ledger"] == before["ledger"] and after["balance"] == before["balance"]
    if initial == "succeeded":
        assert after == before
    rows = await warnings_for(context)
    assert len(rows) == 1 and rows[0].action == f"payment_webhook.{code}"
    assert caplog.text.count(f"code={code}") == 1
    assert "PRIVATE_GATEWAY_REASON" not in caplog.text


async def test_five_concurrent_simulator_dispatches_credit_once(context):
    responses = await asyncio.gather(
        *(dispatch(context, repeat_count=5) for _ in range(5))
    )
    assert all(
        response.status_code == 200 and response.json()["statuses"] == [200] * 5
        for response in responses
    )
    transactions = {response.json()["gateway_transaction_id"] for response in responses}
    assert len(transactions) == 1
    await assert_state(context, "succeeded", AMOUNT, 1, transactions.pop())


async def test_real_ten_second_delay_keeps_order_pending_until_callback(
    context, monkeypatch
):
    real_sleep = asyncio.sleep
    entered = asyncio.Event()
    started = []

    async def observe_sleep(seconds):
        if seconds == 10:
            started.append(perf_counter())
            entered.set()
        await real_sleep(seconds)

    # Observe the barrier but retain the actual ten-second wait and real dispatch.
    monkeypatch.setattr(fake_gateway.asyncio, "sleep", observe_sleep)
    sending = asyncio.create_task(dispatch(context, delay_seconds=10))
    try:
        await asyncio.wait_for(entered.wait(), 5)
        await assert_state(context, "pending", 0, 0)
        assert not sending.done()
        response = await asyncio.wait_for(sending, 20)
        assert response.status_code == 200 and response.json()["statuses"] == [200]
        assert len(started) == 1 and perf_counter() - started[0] >= 9.5
        await assert_state(
            context, "succeeded", AMOUNT, 1, response.json()["gateway_transaction_id"]
        )
    finally:
        if not sending.done():
            sending.cancel()
        await asyncio.gather(sending, return_exceptions=True)


@pytest.mark.parametrize("signature_kind", ["missing", "wrong"])
async def test_bad_signature_has_no_effect_on_real_order_and_logs_ip(
    context, caplog, signature_kind
):
    before = await snapshot(context)
    body, signature = signed(context)
    headers = (
        {} if signature_kind == "missing" else {SIGNATURE_HEADER: "sha256=" + "f" * 64}
    )
    response = await context.client.post(WEBHOOK, content=body, headers=headers)
    assert response.status_code == 401
    assert await snapshot(context) == before and await warnings_for(context) == []
    assert "client_ip=127.0.0.1" in caplog.text
    assert all(
        private not in caplog.text for private in (SECRET, signature, body.decode())
    )


@pytest.mark.parametrize(
    "invalid",
    [
        "missing_status",
        "negative_amount",
        "bool_amount",
        "unknown_status",
        "not_object",
        "malformed_json",
    ],
)
async def test_authenticated_bad_payload_has_no_financial_effect(context, invalid):
    before = await snapshot(context)
    data = json.loads(signed(context)[0])
    if invalid == "missing_status":
        del data["status"]
    elif invalid == "negative_amount":
        data["amount_vnd"] = -1
    elif invalid == "bool_amount":
        data["amount_vnd"] = True
    elif invalid == "unknown_status":
        data["status"] = "pending"
    elif invalid == "not_object":
        data = [data]
    body = (
        b"{invalid-json" if invalid == "malformed_json" else json.dumps(data).encode()
    )
    signature = "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
    response = await context.client.post(
        WEBHOOK, content=body, headers={SIGNATURE_HEADER: signature}
    )
    assert response.status_code == 400
    assert await snapshot(context) == before and await warnings_for(context) == []


async def test_unknown_order_returns_404_groups_warnings_and_hides_external_data(
    context, caplog
):
    before = await snapshot(context)
    order = "missing-" + uuid4().hex
    body, signature = signed(context, order_id=order)
    for _ in range(5):
        response = await context.client.post(
            WEBHOOK, content=body, headers={SIGNATURE_HEADER: signature}
        )
        assert response.status_code == 404
        assert response.json() == {"status": "not_found", "received": False}
    assert await snapshot(context) == before
    async with SessionFactory() as db:
        rows = list(
            await db.scalars(
                select(AuditLog).where(
                    AuditLog.object_type == "payment_order",
                    AuditLog.object_id == hashlib.sha256(order.encode()).hexdigest(),
                )
            )
        )
    assert len(rows) == 1 and rows[0].action == "payment_webhook.unknown_order"
    assert caplog.text.count("code=unknown_order") == 1
    evidence = caplog.text + str(rows[0].data)
    assert all(
        private not in evidence
        for private in (order, body.decode(), signature, SECRET, "Lý do riêng UTF-8")
    )


@pytest.mark.parametrize("initial", ["pending", "succeeded", "failed", "cancelled"])
async def test_amount_mismatch_checks_money_before_state_and_preserves_success(
    context, initial
):
    if initial != "pending":
        assert (await callback(context, status=initial)).status_code == 200
    before = await snapshot(context)
    for _ in range(5):
        response = await callback(context, amount_vnd=AMOUNT + 1)
        assert response.status_code == 400
        assert response.json() == {
            "status": "succeeded" if initial == "succeeded" else "needs_review",
            "received": False,
        }
    after = await assert_state(
        context,
        "succeeded" if initial == "succeeded" else "needs_review",
        before["balance"],
        len(before["ledger"]),
    )
    assert after["ledger"] == before["ledger"]
    if initial == "succeeded":
        assert after == before
    rows = await warnings_for(context)
    assert len(rows) == 1 and rows[0].action == "payment_webhook.amount_mismatch"


async def test_needs_review_cannot_bypass_signature_amount_or_recover(context):
    body, original_signature = signed(context)
    tampered = body.replace(b"100000", b"100001")
    before = await snapshot(context)
    response = await context.client.post(
        WEBHOOK, content=tampered, headers={SIGNATURE_HEADER: original_signature}
    )
    assert response.status_code == 401 and await snapshot(context) == before
    assert (await callback(context, amount_vnd=AMOUNT + 1)).status_code == 400
    review = await snapshot(context)
    assert (await context.client.post(WEBHOOK, content=body)).status_code == 401
    assert (await callback(context, amount_vnd=AMOUNT + 1)).status_code == 400
    for event in ("succeeded", "failed", "cancelled"):
        for _ in range(2):
            response = await callback(context, status=event)
            assert response.status_code == 200 and response.json() == {
                "status": "needs_review",
                "received": True,
            }
    assert await snapshot(context) == review
    await assert_state(context, "needs_review", 0, 0)
    rows = await warnings_for(context)
    assert len(rows) == 2
    assert {row.action for row in rows} == {
        "payment_webhook.amount_mismatch",
        "payment_webhook.review_callback",
    }


async def test_simulator_does_not_report_success_when_signed_order_is_missing(context):
    # An issued link can outlive a missing order; the real receiver must reject it.
    async with SessionFactory() as db, db.begin():
        await db.execute(delete(WalletTopup).where(WalletTopup.id == context.topup_id))
    response = await dispatch(context)
    assert (
        response.status_code == 502
        and "chưa xác nhận nạp tiền" in response.json()["detail"]
    )
    async with SessionFactory() as db:
        wallet = await db.get(Wallet, context.wallet_id)
        assert wallet.balance_vnd == 0
        assert (
            list(
                await db.scalars(
                    select(WalletLedger.id).where(
                        WalletLedger.wallet_id == context.wallet_id
                    )
                )
            )
            == []
        )
    assert (await context.client.get(f"{TOPUPS}/{context.order_id}")).status_code == 404
