"""T-92 delivery, signed simulator links and receiver failure regressions."""

import hashlib
import hmac
import json
import time
from collections.abc import Iterator
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import httpx
import pytest
from pydantic import HttpUrl

from src.config import get_settings
from src.entrypoints.http import app
from src.modules.identity.models import User
from src.modules.payments import webhook_router
from src.modules.payments.contracts import (
    InvalidWebhookSignature,
    PaymentGatewayUnavailable,
    PaymentRequest,
)
from src.modules.payments.dependencies import get_payment_gateway
from src.modules.payments.fake_gateway import FakeGateway
from src.modules.wallet.models import Wallet
from src.modules.wallet.topup_models import WalletTopup
from src.platform.database.session import SessionFactory


@pytest.fixture(autouse=True)
def fake_settings(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("PAYMENT_GATEWAY", "fake")
    monkeypatch.setenv("PAYMENT_WEBHOOK_SECRET", "t92-isolated-test-secret")
    monkeypatch.setenv("PAYMENT_FAKE_BASE_URL", "http://127.0.0.1:8012")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def link(order: str = "ord-test", expires: int | None = None) -> dict[str, str | int]:
    request = PaymentRequest(
        order_id=order,
        amount_vnd=50000,
        return_url=HttpUrl("http://localhost:5173/wallet/topup/return?source=a%26b"),
    )
    expiry = expires if expires is not None else int(time.time()) + 1000
    return {
        "order_id": order,
        "amount_vnd": request.amount_vnd,
        "return_url": str(request.return_url),
        "expires": expiry,
        "token": FakeGateway().payment_token(request, expiry),
    }


@pytest.mark.asyncio
async def test_configured_public_base_produces_signed_link() -> None:
    gateway = get_payment_gateway()
    assert gateway is not None
    request = PaymentRequest(
        order_id="configured-order",
        amount_vnd=50000,
        return_url=get_settings().payment_return_url,
    )
    redirect = await gateway.create_payment(request)
    parsed = urlsplit(str(redirect.redirect_url))
    assert parsed.netloc == "127.0.0.1:8012"
    query = parse_qs(parsed.query)
    assert FakeGateway().verify_payment_token(
        request, int(query["expires"][0]), query["token"][0]
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,value",
    [
        ("amount_vnd", 100000),
        ("order_id", "other-order"),
        ("return_url", "https://attacker.example/"),
        ("expires", 9999999999),
        ("token", "a" * 64),
    ],
)
async def test_browser_cannot_tamper_with_signed_order(
    field: str, value: str | int
) -> None:
    data = {**link(), field: value}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://localhost:8012"
    ) as client:
        assert (
            await client.get("/api/v1/payments/fake/pay", params=data)
        ).status_code == 403
        assert (
            await client.post(
                "/api/v1/payments/fake/dispatch", json={**data, "status": "succeeded"}
            )
        ).status_code == 403


@pytest.mark.asyncio
async def test_expired_link_rejected_and_return_url_not_double_decoded() -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://localhost:8012"
    ) as client:
        assert (
            await client.get(
                "/api/v1/payments/fake/pay", params=link(expires=int(time.time()) - 1)
            )
        ).status_code == 403
        page = await client.get(
            "/api/v1/payments/fake/pay",
            params=link('order"</script><script>throw 1</script>'),
        )
        assert page.status_code == 200
        assert "source=a%26b" in page.text
        assert "<script>throw 1</script>" not in page.text
        assert "const orderId = document." in page.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,value",
    [
        ("webhook_url", "http://169.254.169.254/"),
        ("gateway_transaction_id", "forged-tx"),
        ("amount_vnd", True),
        ("amount_vnd", "50000"),
        ("repeat_count", True),
        ("delay_seconds", 11),
    ],
)
async def test_dispatch_rejects_target_override_and_invalid_types(
    field: str, value: object
) -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://localhost:8012"
    ) as client:
        assert (
            await client.post(
                "/api/v1/payments/fake/dispatch",
                json={**link(), "status": "succeeded", field: value},
            )
        ).status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["succeeded", "failed", "cancelled"])
async def test_dispatch_works_on_real_host_and_stable_transaction_across_replays(
    status: str,
) -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://localhost:8012"
    ) as client:
        order = str(uuid4())
        async with SessionFactory() as db, db.begin():
            user = User(
                email=f"hardening-{uuid4()}@example.com", password_hash="unused"
            )
            db.add(user)
            await db.flush()
            db.add(Wallet(driver_id=user.id))
            db.add(WalletTopup(driver_id=user.id, order_id=order, amount_vnd=50000))
        data = {**link(order), "status": status, "repeat_count": 5}
        first = await client.post("/api/v1/payments/fake/dispatch", json=data)
        second = await client.post("/api/v1/payments/fake/dispatch", json=data)
        assert first.status_code == second.status_code == 200
        assert first.json()["statuses"] == [200] * 5
        assert (
            first.json()["gateway_transaction_id"]
            == second.json()["gateway_transaction_id"]
        )
        assert "signature" not in first.json()


@pytest.mark.asyncio
async def test_dispatch_reports_receiver_rejection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def reject(*args: object) -> None:
        raise InvalidWebhookSignature("bad signature")

    gateway = FakeGateway()
    monkeypatch.setattr(gateway, "verify_webhook", reject)
    monkeypatch.setattr(webhook_router, "get_payment_gateway", lambda: gateway)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://localhost:8012"
    ) as client:
        result = await client.post(
            "/api/v1/payments/fake/dispatch", json={**link(), "status": "succeeded"}
        )
        assert result.status_code == 502
        assert "signature" not in result.text


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [301, 400, 401, 409, 500])
async def test_adapter_never_claims_delivery_for_rejected_http(
    status_code: int,
) -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(status_code))
    ) as client:
        with pytest.raises(PaymentGatewayUnavailable):
            await FakeGateway().dispatch_webhook(
                "ord-test", 50000, "succeeded", client=client
            )


@pytest.mark.asyncio
async def test_delay_and_repeat_send_identical_raw_signed_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleeps: list[float] = []
    captured: list[bytes] = []

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr("src.modules.payments.fake_gateway.asyncio.sleep", sleep)

    def receive(request: httpx.Request) -> httpx.Response:
        body = request.content
        expected = (
            "sha256="
            + hmac.new(b"t92-isolated-test-secret", body, hashlib.sha256).hexdigest()
        )
        assert request.headers["X-Payment-Signature"] == expected
        assert json.loads(body)["reason"] == "Thử độ trễ"
        captured.append(body)
        return httpx.Response(200)

    async with httpx.AsyncClient(transport=httpx.MockTransport(receive)) as client:
        await FakeGateway().dispatch_webhook(
            "ord-test",
            50000,
            "failed",
            reason="Thử độ trễ",
            repeat_count=5,
            delay_seconds=10,
            client=client,
        )
    assert sleeps == [10]
    assert len(captured) == 5
    assert len(set(captured)) == 1


@pytest.mark.asyncio
async def test_network_failure_translates_to_gateway_unavailable() -> None:
    def fail(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("unavailable", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(fail)) as client:
        with pytest.raises(PaymentGatewayUnavailable):
            await FakeGateway().dispatch_webhook(
                "ord-test", 50000, "succeeded", client=client
            )


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["disabled", "sandbox"])
async def test_all_simulator_routes_hidden_outside_fake_mode(
    mode: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = link()
    monkeypatch.setenv("PAYMENT_GATEWAY", mode)
    get_settings.cache_clear()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://localhost:8012"
    ) as client:
        assert (
            await client.get("/api/v1/payments/fake/pay", params=data)
        ).status_code == 404
        assert (
            await client.post(
                "/api/v1/payments/fake/dispatch", json={**data, "status": "succeeded"}
            )
        ).status_code == 404
