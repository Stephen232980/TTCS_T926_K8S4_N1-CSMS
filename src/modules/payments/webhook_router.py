"""Payment webhook receiver endpoint (T-95 verification endpoint)."""

from typing import Any

from fastapi import APIRouter, HTTPException, Request, status

from src.config import get_settings
from src.modules.identity.authorization import AccessPolicy, access_policy
from src.modules.payments.contracts import (
    SIGNATURE_HEADER,
    InvalidWebhookPayload,
    InvalidWebhookSignature,
)
from src.modules.payments.dependencies import get_payment_gateway
from src.modules.payments.fake_gateway import FakeGateway

router = APIRouter(prefix="/api/v1/payments", tags=["payments"])


@router.post("/webhook")
@access_policy(AccessPolicy("public", note="T-95 payment webhook endpoint"))
async def receive_payment_webhook(request: Request) -> dict[str, Any]:
    """Receive and verify payment webhook signature and payload schema."""
    raw_sig_headers = [
        value
        for name, value in request.headers.items()
        if name.lower() == SIGNATURE_HEADER.lower()
    ]
    if len(raw_sig_headers) != 1:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid webhook signature",
        )

    raw_body = await request.body()
    gateway = get_payment_gateway()

    if gateway is None:
        settings = get_settings()
        if settings.payment_webhook_secret is not None:
            gateway = FakeGateway(secret=settings.payment_webhook_secret)
        else:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Payment gateway unavailable",
            )

    try:
        event = gateway.verify_webhook(raw_body, request.headers)
    except InvalidWebhookSignature as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid webhook signature",
        ) from error
    except (InvalidWebhookPayload, ValueError) as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid webhook payload",
        ) from error

    return {
        "status": "ok",
        "received": True,
        "gateway_transaction_id": event.gateway_transaction_id,
        "order_id": event.order_id,
        "amount_vnd": event.amount_vnd,
        "payment_status": event.status,
        "reason": event.reason,
    }
