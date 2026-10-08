"""All runtime balance changes belong here, in the caller's transaction."""

from typing import Literal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.identity.authorization import AuthorizationEvidence
from src.modules.identity.models import Role, User, UserRole
from src.modules.wallet.exceptions import (
    WalletAdjustmentAuditError,
    WalletAdminRequiredError,
    WalletAmountError,
    WalletLedgerConflictError,
    WalletLockedError,
    WalletNotFoundError,
)
from src.modules.wallet.models import Wallet, WalletAudit, WalletLedger
from src.platform.audit.service import ghi_nhat_ky

EntryType = Literal["gateway_topup", "manual_topup", "charging_debit", "adjustment"]
MIN_VND = -(2**63)
MAX_VND = 2**63 - 1


def _integer_vnd(value: int) -> int:
    if type(value) is not int or not MIN_VND <= value <= MAX_VND:
        raise WalletAmountError("Money must be an integer within signed BIGINT range")
    return value


async def _lock_wallet(session: AsyncSession, wallet_id: UUID) -> Wallet:
    wallet = await session.scalar(
        select(Wallet)
        .where(Wallet.id == wallet_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if wallet is None:
        raise WalletNotFoundError("Wallet does not exist")
    return wallet


async def _require_admin(session: AsyncSession, actor_id: UUID | None) -> None:
    admin = await session.scalar(
        select(User.id)
        .join(UserRole, UserRole.user_id == User.id)
        .join(Role, Role.id == UserRole.role_id)
        .where(User.id == actor_id, User.status == "active", Role.code == "admin")
    )
    if admin is None:
        raise WalletAdminRequiredError("An active administrator is required")


def _matching_entry(
    row: WalletLedger, wallet_id: UUID, amount_vnd: int
) -> WalletLedger:
    if row.wallet_id != wallet_id or row.amount_vnd != amount_vnd:
        raise WalletLedgerConflictError(
            "Ledger key already belongs to a different wallet or amount"
        )
    return row


async def ghi_so_cai(
    session: AsyncSession,
    *,
    wallet_id: UUID,
    entry_type: EntryType,
    amount_vnd: int,
    reference_type: str,
    reference_id: str,
    actor_id: UUID | None = None,
) -> WalletLedger:
    """Flush ledger and balance together; never commit the caller's transaction.

    One key is global across wallets. PostgreSQL ON CONFLICT handles races
    between different wallet locks without aborting the outer transaction.
    """
    _integer_vnd(amount_vnd)
    if entry_type not in {
        "gateway_topup",
        "manual_topup",
        "charging_debit",
        "adjustment",
    }:
        raise ValueError("Unknown ledger type")
    if (
        amount_vnd == 0
        or (entry_type in {"gateway_topup", "manual_topup"} and amount_vnd < 0)
        or (entry_type == "charging_debit" and amount_vnd > 0)
    ):
        raise WalletAmountError(
            "Amount sign does not match ledger type; zero invoices must skip the ledger"
        )
    if not isinstance(reference_type, str) or not isinstance(reference_id, str):
        raise TypeError("Ledger references must be strings")
    reference_type, reference_id = reference_type.strip(), reference_id.strip()
    if (
        not reference_type
        or len(reference_type) > 50
        or not reference_id
        or len(reference_id) > 128
    ):
        raise ValueError("Invalid ledger reference")
    wallet = await _lock_wallet(session, wallet_id)
    existing = await session.scalar(
        select(WalletLedger).where(
            WalletLedger.entry_type == entry_type,
            WalletLedger.reference_id == reference_id,
        )
    )
    if existing is not None:
        _matching_entry(existing, wallet_id, amount_vnd)
    if wallet.status == "locked" and entry_type != "adjustment":
        raise WalletLockedError("Wallet is locked")
    audit = None
    if entry_type == "adjustment":
        await _require_admin(session, actor_id)
        try:
            audit_id = UUID(reference_id)
        except ValueError as error:
            raise WalletAdjustmentAuditError(
                "Adjustment reference must be an audit UUID"
            ) from error
        if reference_type != "audit" or str(audit_id) != reference_id:
            raise WalletAdjustmentAuditError(
                "Use the canonical audit UUID as reference"
            )
        audit = await session.get(WalletAudit, audit_id)
        if (
            audit is None
            or audit.action != "adjustment_authorized"
            or audit.wallet_id != wallet_id
            or audit.actor_id != actor_id
            or audit.amount_vnd != amount_vnd
        ):
            raise WalletAdjustmentAuditError(
                "Adjustment audit does not match this operation"
            )
    if existing is not None:
        return existing
    balance_after = _integer_vnd(wallet.balance_vnd + amount_vnd)
    if audit is not None and (
        audit.before_balance_vnd != wallet.balance_vnd
        or audit.after_balance_vnd != balance_after
    ):
        raise WalletAdjustmentAuditError("Adjustment audit balance is stale")
    async with session.begin_nested():
        row: WalletLedger | None = await session.scalar(
            insert(WalletLedger)
            .values(
                wallet_id=wallet_id,
                entry_type=entry_type,
                amount_vnd=amount_vnd,
                balance_after_vnd=balance_after,
                reference_type=reference_type,
                reference_id=reference_id,
                actor_id=actor_id,
            )
            .on_conflict_do_nothing(constraint="uq_wallet_ledger_reference")
            .returning(WalletLedger)
        )
        if row is None:
            winner = await session.scalar(
                select(WalletLedger).where(
                    WalletLedger.entry_type == entry_type,
                    WalletLedger.reference_id == reference_id,
                )
            )
            if winner is None:
                raise WalletLedgerConflictError(
                    "Ledger winner is unavailable; roll back and retry the transaction"
                )
            return _matching_entry(winner, wallet_id, amount_vnd)
        wallet.balance_vnd = balance_after
        await session.flush()
    return row


async def phuc_hoi_so_du_cache(
    session: AsyncSession,
    *,
    wallet_id: UUID,
    actor_id: UUID,
    reason: str,
    authorization: AuthorizationEvidence | None = None,
) -> Wallet:
    """Repair only the cached balance, with audit; never unlock or add money.

    T-87 must first confirm the underlying ledger is correct. This function
    cannot repair business errors or broken invoice references.
    """
    if not isinstance(reason, str) or not reason.strip() or len(reason.strip()) > 500:
        raise ValueError("A repair reason of 1-500 characters is required")
    await _require_admin(session, actor_id)
    wallet = await _lock_wallet(session, wallet_id)
    total = await session.scalar(
        select(func.coalesce(func.sum(WalletLedger.amount_vnd), 0)).where(
            WalletLedger.wallet_id == wallet_id
        )
    )
    balance = _integer_vnd(int(total or 0))
    if wallet.balance_vnd == balance:
        return wallet
    async with session.begin_nested():
        audit = WalletAudit(
            wallet_id=wallet.id,
            actor_id=actor_id,
            action="cache_repaired",
            before_balance_vnd=wallet.balance_vnd,
            after_balance_vnd=balance,
            reason=reason.strip(),
        )
        session.add(audit)
        wallet.balance_vnd = balance
        await session.flush()
        await ghi_nhat_ky(
            session,
            actor_id=actor_id,
            action="wallet.cache_repaired",
            object_type="wallet_audit",
            object_id=str(audit.id),
            data={
                "wallet_id": str(wallet.id),
                "before_balance_vnd": audit.before_balance_vnd,
                "after_balance_vnd": audit.after_balance_vnd,
            },
            permission=authorization.permission if authorization else None,
            actor_roles=authorization.roles if authorization else None,
        )
    return wallet
