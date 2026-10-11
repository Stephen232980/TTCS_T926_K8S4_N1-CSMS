"""Own-wallet payment requests; a redirect is not a wallet credit."""

import asyncio
from datetime import datetime
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, HttpUrl, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.modules.identity.authorization import user_policy
from src.modules.identity.dependencies import CurrentActorDependency, authorize_request
from src.modules.identity.policy_routing import PolicyRoute
from src.modules.payments.contracts import (
    AmountVnd,
    PaymentGateway,
    PaymentGatewayUnavailable,
    PaymentRequest,
)
from src.modules.payments.dependencies import get_payment_gateway
from src.modules.wallet.provisioning import (
    WalletDriverRequiredError,
    ensure_driver_wallet,
)
from src.modules.wallet.topup_models import WalletTopup
from src.platform.database.session import get_db_session

router = APIRouter(
    route_class=PolicyRoute,
    prefix="/api/v1/driver/wallet/topups",
    tags=["driver-wallet"],
    dependencies=[Depends(authorize_request)],
)
Database = Annotated[AsyncSession, Depends(get_db_session)]
Gateway = Annotated[PaymentGateway | None, Depends(get_payment_gateway)]
PAYMENT_CREATE_TIMEOUT_SECONDS = 10.0
TopupStatus = Literal["pending", "succeeded", "failed", "cancelled", "needs_review"]


class TopupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    amount_vnd: AmountVnd

    @model_validator(mode="before")
    @classmethod
    def reject_wallet_selector(cls, value: object) -> object:
        if isinstance(value, dict) and {"wallet_id", "driver_id"} & value.keys():
            raise HTTPException(403, "Không được chỉ định ví hoặc tài xế")
        return value


class TopupResponse(BaseModel):
    order_id: str
    amount_vnd: int
    status: TopupStatus
    reason: str | None
    created_at: datetime


class TopupCreatedResponse(TopupResponse):
    redirect_url: HttpUrl


def check_selectors(request: Request) -> None:
    if {"wallet_id", "driver_id"} & request.query_params.keys():
        raise HTTPException(403, "Không được chỉ định ví hoặc tài xế")


def response(topup: WalletTopup) -> TopupResponse:
    return TopupResponse.model_validate(
        {
            "order_id": topup.order_id,
            "amount_vnd": topup.amount_vnd,
            "status": topup.status,
            "reason": topup.reason,
            "created_at": topup.created_at,
        }
    )


@router.post("", response_model=TopupCreatedResponse, status_code=201)
@user_policy("driver.wallet.topup", "own_wallet", "driver")
async def create_topup(
    request: Request,
    body: TopupRequest,
    actor: CurrentActorDependency,
    db: Database,
    gateway: Gateway,
) -> TopupCreatedResponse:
    check_selectors(request)
    if (
        not settings.wallet_topup_min_vnd
        <= body.amount_vnd
        <= settings.wallet_topup_max_vnd
    ):
        raise HTTPException(422, "Số tiền nạp nằm ngoài ngưỡng cho phép")
    if gateway is None:
        raise HTTPException(503, "Cổng thanh toán chưa khả dụng")
    try:
        wallet = await ensure_driver_wallet(db, actor.user_id)
    except WalletDriverRequiredError as exc:
        raise HTTPException(403, "Tài khoản không có ví tài xế hợp lệ") from exc
    topup = WalletTopup(
        driver_id=wallet.driver_id,
        amount_vnd=body.amount_vnd,
        order_id="topup-" + uuid4().hex,
        status="pending",
    )
    db.add(topup)
    # Publish the order and release provisioning locks before external I/O:
    # a gateway webhook can arrive while create_payment is still awaiting.
    await db.commit()
    payment_request = PaymentRequest(
        order_id=topup.order_id,
        amount_vnd=topup.amount_vnd,
        return_url=settings.payment_return_url,
    )
    try:
        async with asyncio.timeout(PAYMENT_CREATE_TIMEOUT_SECONDS):
            redirect = await gateway.create_payment(payment_request)
    except (PaymentGatewayUnavailable, TimeoutError) as exc:
        # A timeout cannot prove rejection. Keep pending for later reconciliation.
        raise HTTPException(
            503,
            {
                "message": "Cổng thanh toán chưa xác nhận; kiểm tra lại lệnh nạp",
                "order_id": topup.order_id,
            },
        ) from exc
    await db.refresh(topup)
    return TopupCreatedResponse(
        **response(topup).model_dump(), redirect_url=redirect.redirect_url
    )


@router.get("/{order_id}", response_model=TopupResponse)
@user_policy("driver.wallet.topup.read", "own_wallet", "driver")
async def get_topup(
    order_id: str,
    request: Request,
    actor: CurrentActorDependency,
    db: Database,
) -> TopupResponse:
    check_selectors(request)
    topup = await db.scalar(
        select(WalletTopup).where(
            WalletTopup.order_id == order_id,
            WalletTopup.driver_id == actor.user_id,
        )
    )
    if topup is None:
        raise HTTPException(404, "Không tìm thấy lệnh nạp")
    return response(topup)
