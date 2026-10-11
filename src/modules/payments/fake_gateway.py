"""T-92 Fake payment gateway adapter implementing PaymentGateway protocol."""

import asyncio
import hashlib
import hmac
import json
import time
from collections.abc import Mapping
from typing import Any
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

import httpx
from pydantic import HttpUrl, SecretStr

from src.config import get_settings
from src.modules.payments.contracts import (
    SIGNATURE_HEADER,
    GatewayEvent,
    InvalidWebhookPayload,
    PaymentGateway,
    PaymentGatewayUnavailable,
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
        expires = int(time.time()) + 1800
        token = self.payment_token(request, expires)
        pay_url = (
            f"{self.base_url}/api/v1/payments/fake/pay"
            f"?order_id={quote(request.order_id, safe='')}"
            f"&amount_vnd={request.amount_vnd}"
            f"&return_url={encoded_return_url}"
            f"&expires={expires}&token={token}"
        )
        return PaymentRedirect(redirect_url=HttpUrl(pay_url))

    def payment_token(self, request: PaymentRequest, expires: int) -> str:
        """Bind the simulator to the server-issued order, amount and return URL."""
        body = json.dumps(
            [request.order_id, request.amount_vnd, str(request.return_url), expires],
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        return hmac.new(
            self._get_secret().get_secret_value().encode("utf-8"),
            b"csms-fake-payment-link-v1:" + body,
            hashlib.sha256,
        ).hexdigest()

    def verify_payment_token(
        self, request: PaymentRequest, expires: int, token: str
    ) -> bool:
        return expires >= int(time.time()) and hmac.compare_digest(
            token, self.payment_token(request, expires)
        )

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
        if not 1 <= repeat_count <= 10 or not 0 <= delay_seconds <= 60:
            raise ValueError("invalid simulator repeat or delay")
        tx_id = gateway_transaction_id or (
            "fake-tx-" + hashlib.sha256(order_id.encode("utf-8")).hexdigest()[:32]
        )
        payload = GatewayEvent(
            gateway_transaction_id=tx_id,
            order_id=order_id,
            amount_vnd=amount_vnd,
            status=status,
            reason=reason,
        ).model_dump(exclude_none=True)

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

        async def send(http_client: httpx.AsyncClient) -> None:
            for _ in range(repeat_count):
                response = await http_client.post(
                    target_url, content=raw_body, headers=headers
                )
                statuses.append(response.status_code)
                if not response.is_success:
                    raise PaymentGatewayUnavailable("webhook receiver rejected event")

        try:
            if client is not None:
                await send(client)
            else:
                async with httpx.AsyncClient(
                    timeout=15.0, follow_redirects=False
                ) as http_client:
                    await send(http_client)
        except httpx.HTTPError as error:
            raise PaymentGatewayUnavailable("webhook receiver unavailable") from error

        return {
            "gateway_transaction_id": tx_id,
            "payload": payload,
            "signature": signature,
            "repeat_count": repeat_count,
            "statuses": statuses,
        }
