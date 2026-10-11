"""T-95 settlement and T-96 database idempotency; caller owns the transaction."""

import hashlib
from dataclasses import dataclass

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.payments.contracts import GatewayEvent
from src.modules.wallet.exceptions import WalletError, WalletNotFoundError
from src.modules.wallet.models import Wallet
from src.modules.wallet.service import ghi_so_cai
from src.modules.wallet.topup_models import WalletTopup
from src.platform.audit.models import AuditLog
from src.platform.audit.service import ghi_nhat_ky

WARNING_REASONS = {
    "unknown_order": "Payment webhook references an unknown order",
    "amount_mismatch": "Gateway amount does not match the order",
    "gateway_conflict": "Order has a different gateway transaction",
    "late_success": "Success received after failure or cancellation",
    "late_non_success": "Failure or cancellation received after success",
    "review_callback": "Callback received for an order awaiting review",
    "settlement_conflict": "Wallet settlement conflict",
}

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
class WebhookWarning:
    order_reference: str
    code: str


@dataclass(frozen=True)
class SettlementResult:
    status_code: int
    status: str
    warning: WebhookWarning | None = None


async def _warn_once(
    session: AsyncSession, order_id: str, topup: WalletTopup | None, code: str
) -> WebhookWarning | None:
    """Persist one warning per order/category in the settlement transaction.

    Existing orders are already row-locked. Unknown orders use a transaction
    advisory lock so concurrent retries cannot create duplicate audit entries.
    External identifiers are hashed; only fixed, safe reasons are recorded.
    """
    if topup is None:
        reference = hashlib.sha256(order_id.encode()).hexdigest()
        await session.execute(
            text("SELECT pg_advisory_xact_lock(:key)"),
            {"key": int.from_bytes(bytes.fromhex(reference[:16]), signed=True)},
        )
        object_type = "payment_order"
    else:
        reference = str(topup.id)
        object_type = "wallet_topup"
    action = f"payment_webhook.{code}"
    # A retry of an anomaly that already marked review is not a new warning.
    # The original durable evidence also covers callbacks while awaiting review.
    actions = [action]
    if code == "review_callback":
        actions.extend(
            f"payment_webhook.{previous}"
            for previous in ("late_success", "settlement_conflict")
        )
    found = await session.scalar(
        select(AuditLog.id)
        .where(
            AuditLog.action.in_(actions),
            AuditLog.object_type == object_type,
            AuditLog.object_id == reference,
        )
        .limit(1)
    )
    if found is not None:
        return None
    await ghi_nhat_ky(
        session,
        actor_id=None,
        action=action,
        object_type=object_type,
        object_id=reference,
        data={"reason": WARNING_REASONS[code]},
    )
    return WebhookWarning(reference, code)


async def _review(
    session: AsyncSession, topup: WalletTopup, code: str
) -> WebhookWarning | None:
    # Never downgrade a completed credit. Persist only a safe, fixed reason.
    if topup.status not in {"succeeded", "needs_review"}:
        topup.status = "needs_review"
        topup.reason = WARNING_REASONS[code]
        await session.flush()
    return await _warn_once(session, topup.order_id, topup, code)


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
        warning = await _warn_once(session, event.order_id, None, "unknown_order")
        return SettlementResult(404, "not_found", warning)

    if topup.amount_vnd != event.amount_vnd:
        warning = await _review(session, topup, "amount_mismatch")
        return SettlementResult(400, topup.status, warning)

    if topup.gateway_transaction_id not in {None, event.gateway_transaction_id}:
        warning = await _review(session, topup, "gateway_conflict")
        return SettlementResult(200, topup.status, warning)

    next_status = TRANSITIONS[topup.status][event.status]
    # A matching successful replay returns before any ledger/balance/order write.
    if topup.status != "pending":
        warning = None
        if topup.status == "needs_review":
            warning = await _warn_once(
                session, topup.order_id, topup, "review_callback"
            )
        elif next_status == "needs_review":
            warning = await _review(session, topup, "late_success")
        elif topup.status == "succeeded" and event.status != "succeeded":
            warning = await _warn_once(
                session, topup.order_id, topup, "late_non_success"
            )
        return SettlementResult(200, topup.status, warning)

    topup_id = topup.id
    warning = None
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
        warning = await _review(session, topup, "settlement_conflict")
    return SettlementResult(200, topup.status, warning)
