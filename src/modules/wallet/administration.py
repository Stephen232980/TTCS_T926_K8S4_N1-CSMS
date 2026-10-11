"""Separate administrative commands; each participates in the caller's transaction."""

from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.identity.authorization import AuthorizationEvidence
from src.modules.identity.models import Role, UserRole
from src.modules.wallet.exceptions import (
    WalletAdjustmentAuditError,
    WalletAmountError,
    WalletReconciliationError,
)
from src.modules.wallet.models import Wallet, WalletAudit, WalletLedger
from src.modules.wallet.reconciliation import wallet_issues
from src.modules.wallet.service import (
    _integer_vnd,
    _lock_wallet,
    _require_admin,
    ghi_so_cai,
    phuc_hoi_so_du_cache,
)
from src.platform.audit.service import ghi_nhat_ky


async def _evidence(
    session: AsyncSession, actor_id: UUID, permission: str
) -> AuthorizationEvidence:
    await _require_admin(session, actor_id)
    roles = (
        await session.scalars(
            select(Role.code).join(UserRole).where(UserRole.user_id == actor_id)
        )
    ).all()
    return AuthorizationEvidence(permission, tuple(sorted(roles)))


async def sua_so_du_cache(
    session: AsyncSession, *, wallet_id: UUID, actor_id: UUID, reason: str
) -> Wallet:
    evidence = await _evidence(session, actor_id, "admin.wallet.repair_cache")
    wallet = await _lock_wallet(session, wallet_id)
    _, issues = await wallet_issues(session, wallet)
    invalid = [issue for issue in issues if issue != "balance_mismatch"]
    if invalid:
        raise WalletReconciliationError(invalid)
    return await phuc_hoi_so_du_cache(
        session,
        wallet_id=wallet_id,
        actor_id=actor_id,
        reason=reason,
        authorization=evidence,
    )


async def mo_khoa_vi(
    session: AsyncSession, *, wallet_id: UUID, actor_id: UUID
) -> Wallet:
    evidence = await _evidence(session, actor_id, "admin.wallet.unlock")
    wallet = await _lock_wallet(session, wallet_id)
    total, issues = await wallet_issues(session, wallet)
    if issues:
        raise WalletReconciliationError(issues)
    if wallet.status == "active":
        return wallet
    async with session.begin_nested():
        wallet.status = "active"
        await ghi_nhat_ky(
            session,
            actor_id=actor_id,
            action="wallet.unlocked",
            object_type="wallet",
            object_id=str(wallet.id),
            data={"balance_vnd": wallet.balance_vnd, "ledger_total_vnd": total},
            permission=evidence.permission,
            actor_roles=evidence.roles,
        )
    return wallet


async def dieu_chinh_vi(
    session: AsyncSession,
    *,
    wallet_id: UUID,
    actor_id: UUID,
    amount_vnd: int,
    reason: str,
    audit_id: UUID,
) -> WalletLedger:
    evidence = await _evidence(session, actor_id, "admin.wallet.adjust")
    _integer_vnd(amount_vnd)
    if amount_vnd == 0:
        raise WalletAmountError("Adjustment must be nonzero")
    if not isinstance(reason, str) or not reason.strip() or len(reason.strip()) > 500:
        raise ValueError("A reason of 1-500 characters is required")
    await session.execute(
        text("SELECT pg_advisory_xact_lock(:key)"),
        {"key": audit_id.int % (2**63 - 1)},
    )
    wallet = await _lock_wallet(session, wallet_id)
    previous = await session.get(WalletAudit, audit_id)
    if previous is not None and (
        previous.wallet_id != wallet_id
        or previous.actor_id != actor_id
        or previous.amount_vnd != amount_vnd
        or previous.reason != reason.strip()
        or previous.action != "adjustment_authorized"
    ):
        raise WalletAdjustmentAuditError(
            "Audit ID already belongs to a different adjustment"
        )
    existing = await session.scalar(
        select(WalletLedger).where(
            WalletLedger.entry_type == "adjustment",
            WalletLedger.reference_id == str(audit_id),
        )
    )
    if existing is not None:
        if previous is None:
            raise WalletAdjustmentAuditError("Adjustment evidence is missing")
        return await ghi_so_cai(
            session,
            wallet_id=wallet_id,
            entry_type="adjustment",
            amount_vnd=amount_vnd,
            reference_type="audit",
            reference_id=str(audit_id),
            actor_id=actor_id,
        )
    total, _ = await wallet_issues(session, wallet)
    if total != wallet.balance_vnd:
        raise WalletReconciliationError(["balance_mismatch"])
    after = _integer_vnd(wallet.balance_vnd + amount_vnd)
    async with session.begin_nested():
        if previous is None:
            previous = WalletAudit(
                id=audit_id,
                wallet_id=wallet_id,
                actor_id=actor_id,
                action="adjustment_authorized",
                before_balance_vnd=wallet.balance_vnd,
                after_balance_vnd=after,
                amount_vnd=amount_vnd,
                reason=reason.strip(),
            )
            session.add(previous)
            await session.flush()
        entry = await ghi_so_cai(
            session,
            wallet_id=wallet_id,
            entry_type="adjustment",
            amount_vnd=amount_vnd,
            reference_type="audit",
            reference_id=str(audit_id),
            actor_id=actor_id,
        )
        await ghi_nhat_ky(
            session,
            actor_id=actor_id,
            action="wallet.adjusted",
            object_type="wallet_audit",
            object_id=str(audit_id),
            data={
                "wallet_id": str(wallet_id),
                "ledger_id": entry.id,
                "amount_vnd": amount_vnd,
                "before_balance_vnd": previous.before_balance_vnd,
                "after_balance_vnd": after,
            },
            permission=evidence.permission,
            actor_roles=evidence.roles,
        )
    return entry
