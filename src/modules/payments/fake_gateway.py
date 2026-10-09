"""T-92 Fake payment gateway adapter implementing PaymentGateway protocol."""

import asyncio
import hashlib
import hmac
import json
from collections.abc import Mapping
from typing import Any
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit
from uuid import uuid4

import httpx
from pydantic import HttpUrl, SecretStr

from src.config import get_settings
from src.modules.payments.contracts import (
    SIGNATURE_HEADER,
    GatewayEvent,
    InvalidWebhookPayload,
    PaymentGateway,
    PaymentRedirect,
    PaymentRequest,
    PaymentStatus,
)
from src.modules.payments.signatures import verify_hmac_sha256


def build_return_url(return_url: str | HttpUrl, order_id: str) -> str:
    """Append order_code to return_url while preserving existing query parameters."""
    parsed = urlsplit(str(return_url))
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query["order_code"] = order_id
    new_query = urlencode(query)
    return urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, new_query, parsed.fragment)
    )


class FakeGateway(PaymentGateway):
    """Local simulation gateway for end-to-end payment workflow without real payment partners."""

    def __init__(
        self,
        base_url: str = "http://localhost:8000",
        webhook_url: str = "http://localhost:8000/api/v1/payments/webhook",
        secret: SecretStr | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.webhook_url = webhook_url
        self._secret = secret

    def _get_secret(self) -> SecretStr:
        if self._secret is not None:
            return self._secret
        settings = get_settings()
        if settings.payment_webhook_secret is not None:
            return settings.payment_webhook_secret
        raise ValueError("PAYMENT_WEBHOOK_SECRET is required but not configured")

    async def create_payment(self, request: PaymentRequest) -> PaymentRedirect:
        """Create a redirect to the fake gateway payment page."""
        encoded_return_url = quote(str(request.return_url), safe="")
        pay_url = (
            f"{self.base_url}/api/v1/payments/fake/pay"
            f"?order_id={quote(request.order_id, safe='')}"
            f"&amount_vnd={request.amount_vnd}"
            f"&return_url={encoded_return_url}"
        )
        return PaymentRedirect(redirect_url=HttpUrl(pay_url))

    def verify_webhook(
        self, raw_body: bytes, headers: Mapping[str, str]
    ) -> GatewayEvent:
        """Verify webhook signature on raw bytes and parse authenticated GatewayEvent."""
        secret = self._get_secret()
        verify_hmac_sha256(raw_body, headers, secret)
        try:
            data = json.loads(raw_body)
            if not isinstance(data, dict):
                raise TypeError("Payload must be a JSON object")
            return GatewayEvent.model_validate(data)
        except Exception as error:
            raise InvalidWebhookPayload("invalid webhook payload") from error

    async def dispatch_webhook(
        self,
        order_id: str,
        amount_vnd: int,
        status: PaymentStatus,
        reason: str | None = None,
        gateway_transaction_id: str | None = None,
        webhook_url: str | None = None,
        repeat_count: int = 1,
        delay_seconds: float = 0.0,
        client: httpx.AsyncClient | None = None,
    ) -> dict[str, Any]:
        """Sign and dispatch webhook(s) to the backend webhook endpoint."""
        target_url = webhook_url or self.webhook_url
        tx_id = gateway_transaction_id or f"fake-tx-{uuid4().hex[:16]}"
        payload: dict[str, Any] = {
            "gateway_transaction_id": tx_id,
            "order_id": order_id,
            "amount_vnd": amount_vnd,
            "status": status,
        }
        if reason is not None:
            payload["reason"] = reason

        raw_body = json.dumps(
            payload, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
        secret_bytes = self._get_secret().get_secret_value().encode("utf-8")
        signature = (
            "sha256=" + hmac.new(secret_bytes, raw_body, hashlib.sha256).hexdigest()
        )
        headers = {
            "Content-Type": "application/json",
            SIGNATURE_HEADER: signature,
        }

        if delay_seconds > 0:
            await asyncio.sleep(delay_seconds)

        statuses: list[int] = []
        if client is not None:
            for _ in range(repeat_count):
                response = await client.post(
                    target_url, content=raw_body, headers=headers
                )
                statuses.append(response.status_code)
        else:
            async with httpx.AsyncClient(timeout=15.0) as http_client:
                for _ in range(repeat_count):
                    response = await http_client.post(
                        target_url, content=raw_body, headers=headers
                    )
                    statuses.append(response.status_code)

        return {
            "gateway_transaction_id": tx_id,
            "payload": payload,
            "signature": signature,
            "repeat_count": repeat_count,
            "statuses": statuses,
        }
