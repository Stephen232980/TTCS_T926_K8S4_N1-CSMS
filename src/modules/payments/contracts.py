"""T-90 contract shared by gateway adapters, topup creation and webhook handling."""

from collections.abc import Mapping
from typing import Annotated, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator

Identifier = Annotated[str, Field(strict=True, min_length=1, max_length=128)]
AmountVnd = Annotated[int, Field(strict=True, gt=0, le=2**63 - 1)]
PaymentStatus = Literal["succeeded", "failed", "cancelled"]
SIGNATURE_HEADER = "X-Payment-Signature"


class PaymentContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PaymentRequest(PaymentContractModel):
    order_id: Identifier
    amount_vnd: AmountVnd
    return_url: HttpUrl

    @field_validator("order_id")
    @classmethod
    def validate_order_id(cls, value: str) -> str:
        return validate_identifier(value)

    @field_validator("return_url")
    @classmethod
    def validate_return_url(cls, value: HttpUrl) -> HttpUrl:
        return validate_http_url(value)


class PaymentRedirect(PaymentContractModel):
    redirect_url: HttpUrl

    @field_validator("redirect_url")
    @classmethod
    def validate_redirect_url(cls, value: HttpUrl) -> HttpUrl:
        return validate_http_url(value)


class GatewayEvent(PaymentContractModel):
    gateway_transaction_id: Identifier
    order_id: Identifier
    amount_vnd: AmountVnd
    status: PaymentStatus
    reason: Annotated[str, Field(strict=True, max_length=500)] | None = None

    @field_validator("order_id", "gateway_transaction_id")
    @classmethod
    def validate_ids(cls, value: str) -> str:
        return validate_identifier(value)


def validate_identifier(value: str) -> str:
    if value != value.strip() or any(
        ord(char) < 32 or ord(char) == 127 for char in value
    ):
        raise ValueError(
            "payment identifier must not contain surrounding whitespace or controls"
        )
    return value


def validate_http_url(value: HttpUrl) -> HttpUrl:
    if value.username is not None or value.password is not None or value.fragment:
        raise ValueError("payment URL must not contain credentials or fragment")
    return value


class InvalidWebhookSignature(ValueError):
    """Missing, malformed or incorrect signature; endpoint maps to HTTP 401."""


class InvalidWebhookPayload(ValueError):
    """Authenticated body is invalid; endpoint maps to HTTP 400 without payload logs."""


class PaymentGatewayUnavailable(RuntimeError):
    """Adapter unavailable or disabled; creation endpoint maps to HTTP 503."""


class PaymentGateway(Protocol):
    async def create_payment(self, request: PaymentRequest) -> PaymentRedirect:
        """Create a redirect; propagate a stable order_id for retry/idempotency."""
        ...

    def verify_webhook(
        self, raw_body: bytes, headers: Mapping[str, str]
    ) -> GatewayEvent:
        """Authenticate exact bytes BEFORE JSON parsing; never write wallet data."""
        ...
