"""T-98 Webhook test suite with fake gateway simulator (belonging to S-39).

Contains exactly nine focused tests covering valid status transitions,
authentication, tamper-resistance, duplicate headers, malformed payloads,
and out-of-order state scenarios (failed/cancelled after succeeded, succeeded after failed).
"""

import hashlib
import hmac
import json
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from src.config import get_settings
from src.entrypoints.http import app
from src.modules.payments.contracts import SIGNATURE_HEADER

TEST_SECRET = SecretStr("t98-super-secret-webhook-key-999999")


def _sign(body: bytes, secret: SecretStr = TEST_SECRET) -> str:
    key = secret.get_secret_value().encode("utf-8")
    return "sha256=" + hmac.new(key, body, hashlib.sha256).hexdigest()


def _make_body(
    order_id: str = "order-t98-100",
    amount_vnd: int = 100_000,
    status: str = "succeeded",
    reason: str | None = None,
    gateway_transaction_id: str = "fake-tx-t98-100",
) -> bytes:
    payload: dict[str, Any] = {
        "gateway_transaction_id": gateway_transaction_id,
        "order_id": order_id,
        "amount_vnd": amount_vnd,
        "status": status,
    }
    if reason is not None:
        payload["reason"] = reason
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


@pytest.fixture(autouse=True)
def setup_fake_webhook_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("PAYMENT_GATEWAY", "fake")
    monkeypatch.setenv("PAYMENT_WEBHOOK_SECRET", TEST_SECRET.get_secret_value())
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_01_valid_succeeded_webhook() -> None:
    """Ca 1: Webhook thành công hợp lệ (Happy path) ký đúng HMAC-SHA256."""
    body = _make_body(order_id="ord-01", amount_vnd=200_000, status="succeeded")
    sig = _sign(body)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post(
            "/api/v1/payments/webhook",
            content=body,
            headers={"Content-Type": "application/json", SIGNATURE_HEADER: sig},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "ok"
        assert data["payment_status"] == "succeeded"
        assert data["order_id"] == "ord-01"
        assert data["amount_vnd"] == 200_000


@pytest.mark.asyncio
async def test_02_invalid_signature_rejected() -> None:
    """Ca 2: Webhook sai chữ ký bị từ chối với HTTP 401."""
    body = _make_body(order_id="ord-02", status="succeeded")
    wrong_sig = "sha256=" + "f" * 64

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post(
            "/api/v1/payments/webhook",
            content=body,
            headers={"Content-Type": "application/json", SIGNATURE_HEADER: wrong_sig},
        )
        assert res.status_code == 401
        assert "Invalid webhook signature" in res.json()["detail"]


@pytest.mark.asyncio
async def test_03_missing_signature_header_rejected() -> None:
    """Ca 3: Webhook thiếu header chữ ký bị từ chối với HTTP 401."""
    body = _make_body(order_id="ord-03", status="succeeded")

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post(
            "/api/v1/payments/webhook",
            content=body,
            headers={"Content-Type": "application/json"},
        )
        assert res.status_code == 401


@pytest.mark.asyncio
async def test_04_duplicate_signature_headers_rejected() -> None:
    """Ca 4: Webhook chứa nhiều hơn 1 header chữ ký bị từ chối với HTTP 401."""
    body = _make_body(order_id="ord-04", status="succeeded")
    sig = _sign(body)

    headers = [
        ("Content-Type", "application/json"),
        (SIGNATURE_HEADER, sig),
        (SIGNATURE_HEADER, sig),
    ]

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post(
            "/api/v1/payments/webhook",
            content=body,
            headers=headers,
        )
        assert res.status_code == 401


@pytest.mark.asyncio
async def test_05_invalid_payload_schema_rejected() -> None:
    """Ca 5: Webhook chữ ký đúng nhưng schema JSON sai/thiếu trường bị từ chối 400."""
    # Thiếu status và amount_vnd âm
    bad_payload = {
        "gateway_transaction_id": "tx-bad-schema",
        "order_id": "ord-05",
        "amount_vnd": -5000,
    }
    body = json.dumps(bad_payload).encode("utf-8")
    sig = _sign(body)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post(
            "/api/v1/payments/webhook",
            content=body,
            headers={"Content-Type": "application/json", SIGNATURE_HEADER: sig},
        )
        assert res.status_code == 400
        assert "Invalid webhook payload" in res.json()["detail"]


@pytest.mark.asyncio
async def test_06_valid_failed_webhook_with_reason() -> None:
    """Ca 6: Webhook thất bại hợp lệ kèm diễn giải lý do."""
    reason_msg = "Thẻ ngân hàng không đủ hạn mức thanh toán"
    body = _make_body(
        order_id="ord-06",
        amount_vnd=500_000,
        status="failed",
        reason=reason_msg,
    )
    sig = _sign(body)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post(
            "/api/v1/payments/webhook",
            content=body,
            headers={"Content-Type": "application/json", SIGNATURE_HEADER: sig},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["payment_status"] == "failed"
        assert data["reason"] == reason_msg


@pytest.mark.asyncio
async def test_07_valid_cancelled_webhook_with_reason() -> None:
    """Ca 7: Webhook hủy hợp lệ kèm lý do người dùng hủy."""
    reason_msg = "Khách hàng hủy trên trang ngân hàng"
    body = _make_body(
        order_id="ord-07",
        amount_vnd=350_000,
        status="cancelled",
        reason=reason_msg,
    )
    sig = _sign(body)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post(
            "/api/v1/payments/webhook",
            content=body,
            headers={"Content-Type": "application/json", SIGNATURE_HEADER: sig},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["payment_status"] == "cancelled"
        assert data["reason"] == reason_msg


@pytest.mark.asyncio
async def test_08_failed_or_cancelled_after_succeeded() -> None:
    """Ca 8: Trạng thái thất bại/hủy gửi sau khi đã nhận sự kiện thành công."""
    order_id = "ord-08-transition"
    tx_id = "tx-08-shared-id"

    # Bước 1: Gửi thành công
    body_succ = _make_body(
        order_id=order_id,
        amount_vnd=150_000,
        status="succeeded",
        gateway_transaction_id=tx_id,
    )
    sig_succ = _sign(body_succ)

    # Bước 2: Cổng gửi bản tin thất bại/hủy sau đó
    body_fail = _make_body(
        order_id=order_id,
        amount_vnd=150_000,
        status="failed",
        reason="Hoàn tiền hoặc nghi vấn giao dịch sau khi trừ",
        gateway_transaction_id=tx_id,
    )
    sig_fail = _sign(body_fail)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        res1 = await client.post(
            "/api/v1/payments/webhook",
            content=body_succ,
            headers={"Content-Type": "application/json", SIGNATURE_HEADER: sig_succ},
        )
        assert res1.status_code == 200
        assert res1.json()["payment_status"] == "succeeded"

        res2 = await client.post(
            "/api/v1/payments/webhook",
            content=body_fail,
            headers={"Content-Type": "application/json", SIGNATURE_HEADER: sig_fail},
        )
        # Endpoint xác thực chữ ký và format hợp lệ
        assert res2.status_code == 200
        assert res2.json()["payment_status"] == "failed"


@pytest.mark.asyncio
async def test_09_succeeded_after_failed() -> None:
    """Ca 9: Trạng thái thành công gửi sau khi đã từng có bản tin thất bại."""
    order_id = "ord-09-retry-recovery"
    tx_id = "tx-09-recovery"

    # Bước 1: Ban đầu thất bại
    body_fail = _make_body(
        order_id=order_id,
        amount_vnd=200_000,
        status="failed",
        reason="Thao tác bị gián đoạn",
        gateway_transaction_id=tx_id,
    )
    sig_fail = _sign(body_fail)

    # Bước 2: Cổng chốt thành công sau đó
    body_succ = _make_body(
        order_id=order_id,
        amount_vnd=200_000,
        status="succeeded",
        gateway_transaction_id=tx_id,
    )
    sig_succ = _sign(body_succ)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        res1 = await client.post(
            "/api/v1/payments/webhook",
            content=body_fail,
            headers={"Content-Type": "application/json", SIGNATURE_HEADER: sig_fail},
        )
        assert res1.status_code == 200
        assert res1.json()["payment_status"] == "failed"

        res2 = await client.post(
            "/api/v1/payments/webhook",
            content=body_succ,
            headers={"Content-Type": "application/json", SIGNATURE_HEADER: sig_succ},
        )
        assert res2.status_code == 200
        assert res2.json()["payment_status"] == "succeeded"


@pytest.mark.asyncio
async def test_webhook_replay_idempotency_simulation() -> None:
    """Kiểm tra bổ sung: Gửi lại webhook nhiều lần cùng dữ liệu và mã giao dịch."""
    body = _make_body(order_id="ord-replay", status="succeeded")
    sig = _sign(body)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        for _ in range(5):
            res = await client.post(
                "/api/v1/payments/webhook",
                content=body,
                headers={"Content-Type": "application/json", SIGNATURE_HEADER: sig},
            )
            assert res.status_code == 200
            assert res.json()["gateway_transaction_id"] == "fake-tx-t98-100"
