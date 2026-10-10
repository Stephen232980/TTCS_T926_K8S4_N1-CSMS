"""Payment gateway webhook endpoint for wallet top-ups."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.identity.authorization import AccessPolicy, access_policy
from src.modules.identity.policy_routing import PolicyRoute
from src.modules.payments.contracts import (
    InvalidWebhookPayload,
    InvalidWebhookSignature,
    PaymentGateway,
)
from src.modules.payments.dependencies import get_payment_gateway
from src.modules.wallet.topup_webhook_service import (
    TopupNotFoundError,
    TopupWebhookConflictError,
    process_topup_webhook,
)
from src.platform.database.session import get_db_session

router = APIRouter(
    route_class=PolicyRoute,
    prefix="/api/v1/payments",
    tags=["payment-webhooks"],
)

Database = Annotated[AsyncSession, Depends(get_db_session)]
Gateway = Annotated[PaymentGateway | None, Depends(get_payment_gateway)]


@router.post("/webhook")
@access_policy(AccessPolicy("webhook", note="Payment gateway callback"))
async def payment_webhook(
    request: Request,
    db: Database,
    gateway: Gateway,
) -> dict[str, str]:
    if gateway is None:
        raise HTTPException(status_code=503, detail="Payment gateway unavailable")

    raw_body = await request.body()

    try:
        event = gateway.verify_webhook(raw_body, request.headers)
    except InvalidWebhookSignature as exc:
        raise HTTPException(
            status_code=401, detail="Invalid webhook signature"
        ) from exc
    except InvalidWebhookPayload as exc:
        raise HTTPException(
            status_code=400, detail="Invalid webhook payload"
        ) from exc

    try:
        result = await process_topup_webhook(db, event)
        await db.commit()
    except TopupNotFoundError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=404, detail="Top-up order not found"
        ) from exc
    except TopupWebhookConflictError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=409, detail="Conflicting top-up event"
        ) from exc
    except Exception:
        await db.rollback()
        raise

    return {"result": result}
