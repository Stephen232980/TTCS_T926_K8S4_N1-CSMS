"""T-95 settlement and T-96 database idempotency; caller owns the transaction."""

import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.payments.contracts import GatewayEvent
from src.modules.wallet.exceptions import WalletError, WalletNotFoundError
from src.modules.wallet.models import Wallet
from src.modules.wallet.service import ghi_so_cai
from src.modules.wallet.topup_models import WalletTopup

logger = logging.getLogger(__name__)

# Rows are existing states; columns are authenticated event statuses.
TRANSITIONS = {
    "pending": {"succeeded": "succeeded", "failed": "failed", "cancelled": "cancelled"},
    "succeeded": {
        "succeeded": "succeeded",
        "failed": "succeeded",
        "cancelled": "succeeded",
    },
    "failed": {"succeeded": "needs_review", "failed": "failed", "cancelled": "failed"},
    "cancelled": {
        "succeeded": "needs_review",
        "failed": "cancelled",
        "cancelled": "cancelled",
    },
    "needs_review": {
        "succeeded": "needs_review",
        "failed": "needs_review",
        "cancelled": "needs_review",
    },
}


@dataclass(frozen=True)
class SettlementResult:
    status_code: int
    status: str


async def _review(session: AsyncSession, topup: WalletTopup, reason: str) -> None:
    # Never downgrade a completed credit. Persist only a safe, fixed reason.
    if topup.status not in {"succeeded", "needs_review"}:
        topup.status = "needs_review"
        topup.reason = reason
        await session.flush()
        logger.warning(
            "Payment settlement needs review topup_id=%s reason=%s", topup.id, reason
        )


async def process_topup_webhook(
    session: AsyncSession, event: GatewayEvent
) -> SettlementResult:
    """Serialize callbacks on the order, then atomically record gateway and ledger IDs.

    PostgreSQL locks survive until the caller commits/rolls back. Reload the order
    after waiting for its lock, so a second request sees the first committed state.
    The unique gateway ID also arbitrates races between different orders/wallets.
    """
    topup = await session.scalar(
        select(WalletTopup)
        .where(WalletTopup.order_id == event.order_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if topup is None:
        logger.warning("Payment webhook references an unknown order")
        return SettlementResult(404, "not_found")

    if topup.amount_vnd != event.amount_vnd:
        await _review(session, topup, "Gateway amount does not match the order")
        return SettlementResult(400, topup.status)

    if topup.gateway_transaction_id not in {None, event.gateway_transaction_id}:
        await _review(session, topup, "Order has a different gateway transaction")
        return SettlementResult(200, topup.status)

    next_status = TRANSITIONS[topup.status][event.status]
    # A matching successful replay returns before any ledger/balance/order write.
    if topup.status != "pending":
        if next_status == "needs_review":
            await _review(
                session, topup, "Success received after failure or cancellation"
            )
        return SettlementResult(200, topup.status)

    topup_id = topup.id
    try:
        # Roll back BOTH order changes and wallet credit on domain/unique conflicts.
        async with session.begin_nested():
            topup.gateway_transaction_id = event.gateway_transaction_id
            await session.flush()
            if event.status == "succeeded":
                wallet_id = await session.scalar(
                    select(Wallet.id).where(Wallet.driver_id == topup.driver_id)
                )
                if wallet_id is None:
                    raise WalletNotFoundError("Wallet does not exist")
                await ghi_so_cai(
                    session,
                    wallet_id=wallet_id,
                    entry_type="gateway_topup",
                    amount_vnd=event.amount_vnd,
                    reference_type="gateway_transaction",
                    reference_id=event.gateway_transaction_id,
                )
            topup.status = next_status
            topup.reason = (
                (event.reason or f"Gateway reported {event.status}")
                if event.status != "succeeded"
                else None
            )
            await session.flush()
    except (WalletError, IntegrityError) as error:
        if (
            isinstance(error, IntegrityError)
            and getattr(getattr(error.orig, "diag", None), "constraint_name", None)
            != "uq_wallet_topups_gateway"
        ):
            raise
        topup = await session.get(WalletTopup, topup_id, populate_existing=True)
        assert topup is not None
        await _review(session, topup, "Wallet settlement conflict")
    return SettlementResult(200, topup.status)
