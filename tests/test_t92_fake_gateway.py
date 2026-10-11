"""Comprehensive tests for T-92 Fake payment gateway, UI, and webhook integration."""

import hashlib
import hmac
import time
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from pydantic import HttpUrl, SecretStr

from src.config import get_settings
from src.entrypoints.http import app
from src.modules.identity.models import User
from src.modules.payments.contracts import (
    InvalidWebhookPayload,
    InvalidWebhookSignature,
    PaymentRedirect,
    PaymentRequest,
)
from src.modules.payments.dependencies import get_payment_gateway
from src.modules.payments.fake_gateway import FakeGateway, build_return_url
from src.modules.wallet.models import Wallet
from src.modules.wallet.topup_models import WalletTopup
from src.platform.database.session import SessionFactory

TEST_SECRET = SecretStr("t92-test-webhook-secret-key-123456")


ORDERS = {}


@pytest_asyncio.fixture(autouse=True)
async def persisted_orders():
    # Committed integration data stays in the isolated test DB: ledger is immutable.
    async with SessionFactory() as db, db.begin():
        user = User(email=f"t92-{uuid4()}@example.com", password_hash="unused")
        db.add(user)
        await db.flush()
        db.add(Wallet(driver_id=user.id))
        for order, amount in [
            ("order-t92-1", 50000),
            ("order-t92-2", 100000),
            ("order-t92-3", 150000),
            ("order-repeat-5", 200000),
            ("order-delayed-1", 80000),
            ("topup-dispatch-api", 300000),
        ]:
            ORDERS[order] = f"{order}-{uuid4()}"
            db.add(
                WalletTopup(
                    driver_id=user.id, order_id=ORDERS[order], amount_vnd=amount
                )
            )


def payment_link(
    order_id: str, amount_vnd: int, return_url: str | None = None
) -> dict[str, str | int]:
    payment = PaymentRequest(
        order_id=order_id,
        amount_vnd=amount_vnd,
        return_url=HttpUrl(return_url or str(get_settings().payment_return_url)),
    )
    expires = int(time.time()) + 1800
    return {
        "order_id": order_id,
        "amount_vnd": amount_vnd,
        "return_url": str(payment.return_url),
        "expires": expires,
        "token": FakeGateway().payment_token(payment, expires),
    }


def test_build_return_url() -> None:
    # URL without query
    url1 = "http://localhost:5173/wallet/topup/return"
    res1 = build_return_url(url1, "topup-abc")
    assert res1 == "http://localhost:5173/wallet/topup/return?order_code=topup-abc"

    # URL with existing query
    url2 = "http://localhost:5173/wallet/topup/return?from=mobile&theme=dark"
    res2 = build_return_url(url2, "topup-xyz")
    parsed = urlsplit(res2)
    qs = parse_qs(parsed.query)
    assert qs["from"] == ["mobile"]
    assert qs["theme"] == ["dark"]
    assert qs["order_code"] == ["topup-xyz"]


@pytest.mark.asyncio
async def test_fake_gateway_create_payment() -> None:
    gateway = FakeGateway(
        base_url="http://localhost:8000",
        secret=TEST_SECRET,
    )
    request = PaymentRequest(
        order_id="order-test-1",
        amount_vnd=100_000,
        return_url=HttpUrl("http://localhost:5173/wallet/topup/return"),
    )
    redirect = await gateway.create_payment(request)
    assert isinstance(redirect, PaymentRedirect)
    redirect_str = str(redirect.redirect_url)
    assert "/api/v1/payments/fake/pay" in redirect_str
    assert "order_id=order-test-1" in redirect_str
    assert "amount_vnd=100000" in redirect_str
    assert "return_url=" in redirect_str


def test_dependencies_get_payment_gateway(monkeypatch: pytest.MonkeyPatch) -> None:
    # 1. When gateway is 'fake'
    monkeypatch.setenv("PAYMENT_GATEWAY", "fake")
    monkeypatch.setenv("PAYMENT_WEBHOOK_SECRET", "secret-test-abc")
    get_settings.cache_clear()
    gw = get_payment_gateway()
    assert gw is not None
    assert isinstance(gw, FakeGateway)

    # 2. When gateway is 'disabled'
    monkeypatch.setenv("PAYMENT_GATEWAY", "disabled")
    monkeypatch.delenv("PAYMENT_WEBHOOK_SECRET", raising=False)
    get_settings.cache_clear()
    assert get_payment_gateway() is None

    # 3. When gateway is 'sandbox'
    monkeypatch.setenv("PAYMENT_GATEWAY", "sandbox")
    monkeypatch.setenv("PAYMENT_WEBHOOK_SECRET", "secret-test-abc")
    get_settings.cache_clear()
    assert get_payment_gateway() is None

    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_fake_routes_return_404_when_not_fake_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PAYMENT_GATEWAY", "disabled")
    monkeypatch.delenv("PAYMENT_WEBHOOK_SECRET", raising=False)
    get_settings.cache_clear()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # GET pay route
        res_pay = await client.get(
            "/api/v1/payments/fake/pay",
            params={"order_id": "test-1", "amount_vnd": 50000},
        )
        assert res_pay.status_code == 404

        # POST dispatch route
        res_dispatch = await client.post(
            "/api/v1/payments/fake/dispatch",
            json={"order_id": "test-1", "amount_vnd": 50000, "status": "succeeded"},
        )
        assert res_dispatch.status_code == 404

    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_fake_payment_page_renders_html_with_all_elements(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret_value = "super-secret-key-never-leak"
    monkeypatch.setenv("PAYMENT_GATEWAY", "fake")
    monkeypatch.setenv("PAYMENT_WEBHOOK_SECRET", secret_value)
    get_settings.cache_clear()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get(
            "/api/v1/payments/fake/pay",
            params=payment_link(
                "topup-ord-999",
                250_000,
                "http://localhost:5173/wallet/topup/return?source=test",
            ),
        )
        assert res.status_code == 200
        assert "text/html" in res.headers["content-type"]
        html = res.text

        # Verify order info displayed
        assert "topup-ord-999" in html
        assert "250.000" in html

        # Verify all 5 required buttons present
        assert "Thành công" in html
        assert "Thất bại" in html
        assert "Hủy" in html
        assert "Gửi lại webhook 5 lần" in html
        assert "Trễ webhook 10 giây" in html

        # Verify return link with order_code
        assert "order_code=topup-ord-999" in html

        # Verify secret is NEVER leaked to frontend
        assert secret_value not in html

    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_dispatch_webhook_and_webhook_endpoint_verification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PAYMENT_GATEWAY", "fake")
    monkeypatch.setenv("PAYMENT_WEBHOOK_SECRET", TEST_SECRET.get_secret_value())
    get_settings.cache_clear()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        gateway = FakeGateway(
            base_url="http://test",
            webhook_url="http://test/api/v1/payments/webhook",
            secret=TEST_SECRET,
        )

        # 1. Dispatch succeeded webhook
        res1 = await gateway.dispatch_webhook(
            order_id=ORDERS["order-t92-1"],
            amount_vnd=50_000,
            status="succeeded",
            client=client,
        )
        assert res1["repeat_count"] == 1
        assert res1["statuses"] == [200]
        assert res1["payload"]["status"] == "succeeded"
        assert res1["payload"]["order_id"] == ORDERS["order-t92-1"]

        # 2. Dispatch failed webhook with reason
        res2 = await gateway.dispatch_webhook(
            order_id=ORDERS["order-t92-2"],
            amount_vnd=100_000,
            status="failed",
            reason="Không đủ số dư thẻ",
            client=client,
        )
        assert res2["statuses"] == [200]
        assert res2["payload"]["status"] == "failed"
        assert res2["payload"]["reason"] == "Không đủ số dư thẻ"

        # 3. Dispatch cancelled webhook
        res3 = await gateway.dispatch_webhook(
            order_id=ORDERS["order-t92-3"],
            amount_vnd=150_000,
            status="cancelled",
            reason="Người dùng đóng trang",
            client=client,
        )
        assert res3["statuses"] == [200]
        assert res3["payload"]["status"] == "cancelled"

    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_repeat_button_dispatches_exactly_5_times_with_same_transaction_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PAYMENT_GATEWAY", "fake")
    monkeypatch.setenv("PAYMENT_WEBHOOK_SECRET", TEST_SECRET.get_secret_value())
    get_settings.cache_clear()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        gateway = FakeGateway(
            base_url="http://test",
            webhook_url="http://test/api/v1/payments/webhook",
            secret=TEST_SECRET,
        )

        res = await gateway.dispatch_webhook(
            order_id=ORDERS["order-repeat-5"],
            amount_vnd=200_000,
            status="succeeded",
            repeat_count=5,
            client=client,
        )
        assert res["repeat_count"] == 5
        assert len(res["statuses"]) == 5
        assert all(s == 200 for s in res["statuses"])
        assert res["payload"]["gateway_transaction_id"] == res["gateway_transaction_id"]

    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_delayed_webhook_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PAYMENT_GATEWAY", "fake")
    monkeypatch.setenv("PAYMENT_WEBHOOK_SECRET", TEST_SECRET.get_secret_value())
    get_settings.cache_clear()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        gateway = FakeGateway(
            base_url="http://test",
            webhook_url="http://test/api/v1/payments/webhook",
            secret=TEST_SECRET,
        )

        start_time = time.perf_counter()
        # Use 0.1s in test to verify delay logic without slowing down test suite
        res = await gateway.dispatch_webhook(
            order_id=ORDERS["order-delayed-1"],
            amount_vnd=80_000,
            status="succeeded",
            delay_seconds=0.1,
            client=client,
        )
        elapsed = time.perf_counter() - start_time
        assert elapsed >= 0.09
        assert res["statuses"] == [200]

    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_dispatch_api_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PAYMENT_GATEWAY", "fake")
    monkeypatch.setenv("PAYMENT_WEBHOOK_SECRET", TEST_SECRET.get_secret_value())
    get_settings.cache_clear()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post(
            "/api/v1/payments/fake/dispatch",
            json={
                **payment_link(ORDERS["topup-dispatch-api"], 300_000),
                "status": "succeeded",
            },
        )
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "ok"
        assert "fake-tx-" in data["gateway_transaction_id"]
        assert data["repeat_count"] == 1
        assert "signature" not in data

    get_settings.cache_clear()


def test_fake_gateway_verify_webhook_unit() -> None:
    gateway = FakeGateway(secret=TEST_SECRET)
    raw_body = b'{"gateway_transaction_id":"tx-123","order_id":"ord-123","amount_vnd":50000,"status":"succeeded"}'
    key = TEST_SECRET.get_secret_value().encode("utf-8")
    sig = "sha256=" + hmac.new(key, raw_body, hashlib.sha256).hexdigest()
    headers = {"X-Payment-Signature": sig}

    # 1. Valid webhook
    event = gateway.verify_webhook(raw_body, headers)
    assert event.gateway_transaction_id == "tx-123"
    assert event.order_id == "ord-123"
    assert event.amount_vnd == 50_000
    assert event.status == "succeeded"

    # 2. Invalid signature
    with pytest.raises(InvalidWebhookSignature):
        gateway.verify_webhook(raw_body, {"X-Payment-Signature": "sha256=" + "a" * 64})

    # 3. Invalid payload schema (e.g. missing status)
    bad_body = (
        b'{"gateway_transaction_id":"tx-123","order_id":"ord-123","amount_vnd":50000}'
    )
    bad_sig = "sha256=" + hmac.new(key, bad_body, hashlib.sha256).hexdigest()
    with pytest.raises(InvalidWebhookPayload):
        gateway.verify_webhook(bad_body, {"X-Payment-Signature": bad_sig})
