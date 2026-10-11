"""Administrator-triggered, audited VNPAY query and optional settlement."""

import json
from datetime import datetime
from typing import Annotated
from zoneinfo import ZoneInfo

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import get_settings
from src.modules.identity.authorization import user_policy
from src.modules.identity.dependencies import (
    AuditEvidence,
    CurrentActorDependency,
    authorize_request,
)
from src.modules.identity.policy_routing import PolicyRoute
from src.modules.payments.contracts import (
    InvalidWebhookPayload,
    InvalidWebhookSignature,
)
from src.modules.payments.vnpay_query import query_transaction
from src.modules.payments.vnpay_router import gateway
from src.modules.wallet.exceptions import WalletError
from src.modules.wallet.topup_models import WalletTopup
from src.modules.wallet.topup_webhook_service import TRANSITIONS, process_topup_webhook
from src.platform.audit.service import ghi_nhat_ky
from src.platform.database.session import get_db_session

router = APIRouter(
    prefix="/api/v1/admin/payments/vnpay",
    tags=["admin-payments"],
    route_class=PolicyRoute,
    dependencies=[Depends(authorize_request)],
)
Database = Annotated[AsyncSession, Depends(get_db_session)]


class ReconcileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    apply: bool = False
    transaction_date: str | None = Field(default=None, pattern=r"^[0-9]{14}$")

    @field_validator("transaction_date")
    @classmethod
    def valid_date(cls, value: str | None) -> str | None:
        if value is not None:
            datetime.strptime(value, "%Y%m%d%H%M%S").replace(
                tzinfo=ZoneInfo("Asia/Ho_Chi_Minh")
            )
        return value


class ReconcileResponse(BaseModel):
    order_id: str
    status: str
    query_response_code: str
    transaction_status: str | None
    transaction_date: str
    request_id: str
    applied: bool
    requires_review: bool
    amount_vnd: int | None


@router.post("/topups/{order_id}/reconcile", response_model=ReconcileResponse)
@user_policy("admin.wallet.topup.reconcile", "all", "admin")
async def reconcile(
    order_id: str,
    body: ReconcileRequest,
    actor: CurrentActorDependency,
    evidence: AuditEvidence,
    db: Database,
) -> ReconcileResponse:
    adapter = gateway()
    server_ip = get_settings().vnpay_query_ip
    if not server_ip:
        raise HTTPException(503, "VNPAY query server IP is not configured")
    topup = await db.scalar(select(WalletTopup).where(WalletTopup.order_id == order_id))
    if topup is None or not order_id.startswith("vnpay"):
        raise HTTPException(404, "Không tìm thấy lệnh nạp VNPAY")
    transaction_date = body.transaction_date or topup.created_at.astimezone(
        ZoneInfo("Asia/Ho_Chi_Minh")
    ).strftime("%Y%m%d%H%M%S")
    topup_id = str(topup.id)
    # Release the read transaction before external I/O. The shared settlement
    # re-locks/reloads the order and handles an IPN arriving during QueryDR.
    await db.rollback()
    try:
        result = await query_transaction(adapter, order_id, transaction_date, server_ip)
    except (
        httpx.HTTPError,
        InvalidWebhookPayload,
        InvalidWebhookSignature,
        json.JSONDecodeError,
        UnicodeDecodeError,
    ) as exc:
        try:
            await ghi_nhat_ky(
                db,
                actor_id=actor.user_id,
                action="vnpay_reconciliation_query_failed",
                object_type="wallet_topup",
                object_id=topup_id,
                permission=evidence.permission,
                actor_roles=evidence.roles,
                data={
                    "transaction_date": transaction_date,
                    "apply_requested": body.apply,
                    "error_category": type(exc).__name__,
                },
            )
            await db.commit()
        except SQLAlchemyError:
            await db.rollback()
            raise HTTPException(
                503, "Không lưu được lần truy vấn; đơn chưa được cập nhật"
            ) from None
        raise HTTPException(
            502, "Không xác minh được kết quả VNPAY; đơn chưa được cập nhật"
        ) from None
    try:
        topup = await db.scalar(
            select(WalletTopup)
            .where(WalletTopup.order_id == order_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if topup is None:
            raise HTTPException(404, "Không tìm thấy lệnh nạp")
        before = topup.status
        requires_review = topup.status == "needs_review"
        event = result.event
        amount_matches = event is None or event.amount_vnd == topup.amount_vnd
        if not amount_matches:
            requires_review = True
        if event is not None and (
            topup.gateway_transaction_id not in {None, event.gateway_transaction_id}
            or TRANSITIONS[topup.status][event.status] == "needs_review"
        ):
            requires_review = True
        applied = False
        if body.apply and event is not None:
            settlement = await process_topup_webhook(db, event)
            await db.refresh(topup)
            requires_review = (
                settlement.warning is not None or topup.status == "needs_review"
            )
            applied = before == "pending" and topup.status in {"succeeded", "failed"}
        elif result.transaction_status not in {None, "00", "01", "02"}:
            requires_review = True
        await ghi_nhat_ky(
            db,
            actor_id=actor.user_id,
            action="vnpay_reconciliation_applied"
            if body.apply
            else "vnpay_reconciliation_queried",
            object_type="wallet_topup",
            object_id=str(topup.id),
            permission=evidence.permission,
            actor_roles=evidence.roles,
            data={
                "request_id": result.request_id,
                "transaction_date": transaction_date,
                "response_code": result.response_code,
                "transaction_status": result.transaction_status,
                "before": before,
                "after": topup.status,
                "applied": applied,
                "amount_matches": amount_matches,
            },
        )
        response = ReconcileResponse(
            order_id=order_id,
            status=topup.status,
            query_response_code=result.response_code,
            transaction_status=result.transaction_status,
            transaction_date=transaction_date,
            request_id=result.request_id,
            applied=applied,
            requires_review=requires_review,
            amount_vnd=event.amount_vnd if event is not None else None,
        )
        await db.commit()
        return response
    except (SQLAlchemyError, WalletError):
        await db.rollback()
        raise HTTPException(
            503, "Đối soát chưa được lưu; vui lòng truy vấn lại"
        ) from None
