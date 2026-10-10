"""Payment webhook receiver endpoint (T-95 settlement endpoint)."""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.identity.authorization import AccessPolicy, access_policy
from src.modules.payments.contracts import (
    SIGNATURE_HEADER,
    InvalidWebhookPayload,
    InvalidWebhookSignature,
)
from src.modules.payments.dependencies import get_payment_gateway
from src.modules.wallet.topup_webhook_service import process_topup_webhook
from src.platform.database.session import get_db_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/payments", tags=["payments"])


class WebhookResponse(BaseModel):
    status: str
    received: bool


@router.post(
    "/webhook",
    response_model=WebhookResponse,
    responses={
        400: {"description": "Invalid payload or amount mismatch"},
        401: {"description": "Invalid or missing raw-body signature"},
        404: {"description": "Unknown top-up order"},
        503: {"description": "Payment adapter unavailable"},
    },
)
@access_policy(AccessPolicy("public", note="T-95 payment webhook endpoint"))
async def receive_payment_webhook(
    request: Request, session: Annotated[AsyncSession, Depends(get_db_session)]
) -> JSONResponse:
    """Authenticate exact bytes, then atomically settle the persisted order."""
    raw_sig_headers = [
        value
        for name, value in request.headers.items()
        if name.lower() == SIGNATURE_HEADER.lower()
    ]
    if len(raw_sig_headers) != 1:
        logger.warning(
            "Invalid payment signature client_ip=%s",
            request.client.host if request.client else "unknown",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid webhook signature",
        )

    raw_body = await request.body()
    gateway = get_payment_gateway()

    if gateway is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Payment gateway unavailable",
        )

    try:
        event = gateway.verify_webhook(raw_body, request.headers)
    except InvalidWebhookSignature as error:
        logger.warning(
            "Invalid payment signature client_ip=%s",
            request.client.host if request.client else "unknown",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid webhook signature",
        ) from error
    except (InvalidWebhookPayload, ValueError) as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid webhook payload",
        ) from error

    result = await process_topup_webhook(session, event)
    # Commit before acknowledging delivery, including persisted review on HTTP 400.
    await session.commit()
    return JSONResponse(
        status_code=result.status_code,
        content={"status": result.status, "received": result.status_code == 200},
    )
