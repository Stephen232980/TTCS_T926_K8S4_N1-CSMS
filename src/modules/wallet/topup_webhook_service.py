
"""Idempotent processing for verified payment gateway events."""

from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.payments.contracts import GatewayEvent
from src.modules.wallet.exceptions import WalletNotFoundError
from src.modules.wallet.models import Wallet
from src.modules.wallet.service import ghi_so_cai
from src.modules.wallet.topup_models import WalletTopup


WebhookResult = Literal["processed", "duplicate", "amount_mismatch"]


class TopupNotFoundError(Exception):
    """The payment order does not exist."""


class TopupWebhookConflictError(Exception):
    """The event conflicts with the current order state."""


async def process_topup_webhook(
    session: AsyncSession,
    event: GatewayEvent,
) -> WebhookResult:
    """Process an already verified event in the caller's transaction.

    This function never commits. The caller must commit successful results
    and roll back if processing raises an exception.
    """

    # Lock the order so concurrent webhook requests cannot process it twice.
    topup = await session.scalar(
        select(WalletTopup)
        .where(WalletTopup.order_id == event.order_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )

    if topup is None:
        raise TopupNotFoundError("Top-up order does not exist")

    # A previously recorded gateway transaction must not be reused
    # to apply another event to this order.
    if topup.gateway_transaction_id is not None:
        if topup.gateway_transaction_id != event.gateway_transaction_id:
            raise TopupWebhookConflictError(
                "Order already has a different gateway transaction"
            )

        if topup.status == event.status or topup.status == "needs_review":
            return "duplicate"

        raise TopupWebhookConflictError(
            "Gateway event conflicts with the recorded order status"
        )

    # Do not credit an order with a different amount.
    if topup.amount_vnd != event.amount_vnd:
        topup.status = "needs_review"
        topup.gateway_transaction_id = event.gateway_transaction_id
        topup.reason = "Gateway amount does not match the top-up order"
        await session.flush()
        return "amount_mismatch"

    # Do not process a new event against an order that is no longer pending.
    if topup.status != "pending":
        raise TopupWebhookConflictError(
            "Order is no longer pending and has no matching transaction"
        )

    if event.status == "succeeded":
        wallet = await session.scalar(
            select(Wallet).where(Wallet.driver_id == topup.driver_id)
        )

        if wallet is None:
            raise WalletNotFoundError("Wallet does not exist")

        await ghi_so_cai(
            session,
            wallet_id=wallet.id,
            entry_type="gateway_topup",
            amount_vnd=event.amount_vnd,
            reference_type="gateway_transaction",
            reference_id=event.gateway_transaction_id,
        )

    topup.status = event.status
    topup.gateway_transaction_id = event.gateway_transaction_id
    topup.reason = event.reason

    await session.flush()
    return "processed"
