"""Public VNPAY callbacks: IPN settles, Return only navigates."""

import logging
from collections.abc import Callable, Coroutine
from typing import Annotated, Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastapi.routing import APIRoute
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import get_settings
from src.modules.identity.authorization import AccessPolicy, access_policy
from src.modules.payments.contracts import (
    InvalidWebhookPayload,
    InvalidWebhookSignature,
)
from src.modules.payments.dependencies import get_payment_gateway
from src.modules.payments.vnpay_gateway import VnpayGateway
from src.modules.wallet.exceptions import WalletError
from src.modules.wallet.topup_models import WalletTopup
from src.modules.wallet.topup_webhook_service import (
    WARNING_REASONS,
    process_topup_webhook,
)
from src.platform.database.session import get_db_session


class PrivateCallbackRoute(APIRoute):
    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler = super().get_route_handler()

        async def private_handler(request: Request) -> Response:
            request.state.vnpay_params = request.query_params.multi_items()
            # Uvicorn access logs must not print signed URLs (also on errors).
            request.scope["query_string"] = b""
            return await handler(request)

        return private_handler


router = APIRouter(
    prefix="/api/v1/payments/vnpay", tags=["payments"], route_class=PrivateCallbackRoute
)
logger = logging.getLogger(__name__)


def gateway() -> VnpayGateway:
    adapter = get_payment_gateway()
    if not isinstance(adapter, VnpayGateway):
        raise HTTPException(503, "VNPAY sandbox unavailable")
    return adapter


def reply(code: str, message: str) -> JSONResponse:
    # HTTP 200 is transport acknowledgement, RspCode controls VNPAY retries.
    return JSONResponse({"RspCode": code, "Message": message})


@router.get("/ipn")
@access_policy(AccessPolicy("public", note="VNPAY signed GET IPN; no session required"))
async def ipn(
    request: Request, db: Annotated[AsyncSession, Depends(get_db_session)]
) -> JSONResponse:
    adapter = gateway()
    try:
        event = adapter.verify_query(request.state.vnpay_params)
    except InvalidWebhookSignature:
        logger.warning(
            "Invalid VNPAY signature client_ip=%s",
            request.client.host if request.client else "unknown",
        )
        return reply("97", "Invalid signature")
    except InvalidWebhookPayload:
        return reply("99", "Invalid payment data")
    try:
        # Same lock as settlement, so duplicate acknowledgements reflect the
        # committed state even when IPNs arrive concurrently.
        prior = await db.scalar(
            select(WalletTopup)
            .where(WalletTopup.order_id == event.order_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        already_confirmed = prior is not None and prior.status in {
            "succeeded",
            "failed",
            "cancelled",
        }
        result = await process_topup_webhook(db, event)
        await db.commit()
    except (SQLAlchemyError, WalletError):
        await db.rollback()
        # Avoid exception text/traceback: DB errors can contain gateway parameters.
        logger.error("VNPAY IPN settlement failed")
        return reply("99", "Settlement unavailable")
    if result.warning is not None:
        logger.warning(
            "Payment webhook anomaly order_reference=%s code=%s reason=%s",
            result.warning.order_reference,
            result.warning.code,
            WARNING_REASONS[result.warning.code],
        )
    if result.status_code == 404:
        return reply("01", "Order not found")
    if result.status_code == 400:
        return reply("04", "Invalid amount")
    if result.status == "needs_review" or result.warning is not None:
        return reply("99", "Order requires review")
    if already_confirmed:
        return reply("02", "Order already confirmed")
    return reply("00", "Confirm Success")


@router.get("/return")
@access_policy(AccessPolicy("public", note="VNPAY signed Return; navigation only"))
async def payment_return(request: Request) -> RedirectResponse:
    adapter = gateway()
    try:
        event = adapter.verify_query(request.state.vnpay_params)
    except (InvalidWebhookSignature, InvalidWebhookPayload) as exc:
        raise HTTPException(400, "Invalid VNPAY return") from exc
    url = urlsplit(str(get_settings().payment_return_url))
    query = [(k, v) for k, v in parse_qsl(url.query) if k != "order_code"]
    query.append(("order_code", event.order_id))
    return RedirectResponse(
        urlunsplit(url._replace(query=urlencode(query))), status_code=303
    )
