"""Driver wallet and ledger routes with own_wallet policy."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.identity.authorization import user_policy
from src.modules.identity.dependencies import (
    CurrentActorDependency,
    authorize_request,
)
from src.modules.identity.policy_routing import PolicyRoute
from src.modules.wallet.models import Wallet, WalletLedger
from src.modules.wallet.provisioning import ensure_driver_wallet
from src.modules.wallet.schemas import (
    WalletLedgerItemResponse,
    WalletLedgerListResponse,
    WalletResponse,
    WalletTransactionResponse,
)
from src.modules.wallet.topup_models import WalletTopup
from src.platform.database.session import get_db_session

router = APIRouter(
    route_class=PolicyRoute,
    prefix="/api/v1/driver/wallet",
    tags=["driver-wallet"],
    dependencies=[Depends(authorize_request)],
)

Database = Annotated[AsyncSession, Depends(get_db_session)]


def check_wallet_selectors(request: Request) -> None:
    if {"wallet_id", "driver_id"} & request.query_params.keys():
        raise HTTPException(403, "Không được chỉ định ví hoặc tài xế")


def ledger_item(entry: WalletLedger) -> WalletLedgerItemResponse:
    return WalletLedgerItemResponse(
        id=entry.id,
        wallet_id=entry.wallet_id,
        amount_vnd=entry.amount_vnd,
        amount=entry.amount_vnd,
        balance_after_vnd=entry.balance_after_vnd,
        balance_after=entry.balance_after_vnd,
        entry_type=entry.entry_type,
        reference_type=entry.reference_type,
        reference_id=entry.reference_id,
        description=_build_entry_description(entry),
        created_at=entry.created_at,
    )


def _build_entry_description(entry: WalletLedger) -> str:
    if entry.entry_type == "gateway_topup":
        return "Nạp tiền qua cổng thanh toán"
    if entry.entry_type == "manual_topup":
        return "Nạp tiền vào ví"
    if entry.entry_type == "charging_debit":
        return f"Thanh toán phiên sạc ({entry.reference_id})"
    if entry.entry_type == "adjustment":
        return "Điều chỉnh số dư quản trị"
    if entry.entry_type == "reservation_fee":
        return f"Phí không đến của đặt chỗ ({entry.reference_id})"
    if entry.entry_type == "subscription_debit":
        return "Phí gói thuê bao tháng"
    return f"Giao dịch {entry.entry_type}"


@router.get(
    "",
    response_model=WalletResponse,
    description="Driver views own wallet balance and status",
)
@user_policy("driver.wallet.read", "own_wallet", "driver")
async def get_driver_wallet(
    actor: CurrentActorDependency,
    db: Database,
    request: Request,
) -> WalletResponse:
    check_wallet_selectors(request)
    wallet = await ensure_driver_wallet(db, actor.user_id)
    await db.commit()
    await db.refresh(wallet)

    is_neg = wallet.balance_vnd < 0
    debt = abs(wallet.balance_vnd) if is_neg else 0

    return WalletResponse(
        id=wallet.id,
        driver_id=wallet.driver_id,
        balance_vnd=wallet.balance_vnd,
        balance=wallet.balance_vnd,
        currency="VND",
        status=wallet.status,
        is_negative=is_neg,
        debt_amount_vnd=debt,
        debt_amount=debt,
    )


@router.get(
    "/transactions",
    response_model=WalletLedgerListResponse,
    description="Driver views own wallet ledger with cursor pagination",
)
@user_policy("driver.wallet.ledger", "own_wallet", "driver")
async def get_driver_wallet_transactions(
    actor: CurrentActorDependency,
    db: Database,
    request: Request,
    cursor: int | None = Query(None, description="Cursor for pagination (id < cursor)"),
    limit: int = Query(50, ge=1, le=50, description="Page limit"),
) -> WalletLedgerListResponse:
    check_wallet_selectors(request)
    wallet = await ensure_driver_wallet(db, actor.user_id)
    await db.commit()

    stmt = select(WalletLedger).where(WalletLedger.wallet_id == wallet.id)
    if cursor is not None:
        stmt = stmt.where(WalletLedger.id < cursor)

    stmt = stmt.order_by(WalletLedger.id.desc()).limit(limit + 1)
    rows = (await db.scalars(stmt)).all()

    has_more = len(rows) > limit
    page_rows = rows[:limit]
    next_cursor = page_rows[-1].id if has_more and page_rows else None

    items = [ledger_item(row) for row in page_rows]

    return WalletLedgerListResponse(
        items=items,
        next_cursor=next_cursor,
        has_more=has_more,
    )


@router.get("/transactions/{entry_id}", response_model=WalletTransactionResponse)
@user_policy("driver.wallet.ledger", "own_wallet", "driver")
async def get_driver_wallet_transaction(
    entry_id: int,
    actor: CurrentActorDependency,
    db: Database,
    request: Request,
) -> WalletTransactionResponse:
    check_wallet_selectors(request)
    row = (
        await db.execute(
            select(WalletLedger, Wallet.driver_id)
            .join(Wallet, Wallet.id == WalletLedger.wallet_id)
            .where(WalletLedger.id == entry_id)
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(404, "Không tìm thấy giao dịch")
    entry, driver_id = row
    if driver_id != actor.user_id:
        raise HTTPException(403, "Không có quyền xem giao dịch này")
    topup = None
    if entry.entry_type == "gateway_topup":
        topup = await db.scalar(
            select(WalletTopup).where(
                WalletTopup.driver_id == actor.user_id,
                WalletTopup.gateway_transaction_id == entry.reference_id,
            )
        )
    return WalletTransactionResponse(
        **ledger_item(entry).model_dump(),
        topup_order_id=topup.order_id if topup else None,
        topup_status=topup.status if topup else None,
        topup_reason=topup.reason if topup else None,
    )
