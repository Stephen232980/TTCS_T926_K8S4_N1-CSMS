"""Inspect under the wallet lock; never silently repair financial evidence."""

import asyncio
import logging
from uuid import UUID

from sqlalchemy import String, cast, exists, func, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.modules.billing.models import Invoice
from src.modules.charging.models import ChargingSession
from src.modules.wallet.models import Wallet, WalletLedger
from src.modules.wallet.service import MAX_VND, MIN_VND
from src.platform.audit.service import ghi_nhat_ky
from src.platform.database.session import SessionFactory

logger = logging.getLogger("csms.wallet")


async def wallet_issues(session: AsyncSession, wallet: Wallet) -> tuple[int, list[str]]:
    """Caller must hold this wallet's row lock before inspecting the ledger."""
    total = int(
        await session.scalar(
            select(func.coalesce(func.sum(WalletLedger.amount_vnd), 0)).where(
                WalletLedger.wallet_id == wallet.id
            )
        )
        or 0
    )
    issues = set()
    if total != wallet.balance_vnd:
        issues.add("balance_mismatch")
    if not MIN_VND <= total <= MAX_VND:
        issues.add("ledger_total_overflow")
    related_entry = exists(
        select(WalletLedger.id).where(
            WalletLedger.wallet_id == wallet.id,
            WalletLedger.reference_id.in_(
                [cast(ChargingSession.id, String), cast(Invoice.id, String)]
            ),
            or_(
                WalletLedger.entry_type == "charging_debit",
                WalletLedger.reference_type == "charging_session",
            ),
        )
    )
    invoices = (
        await session.execute(
            select(Invoice, ChargingSession)
            .join(ChargingSession, ChargingSession.id == Invoice.session_id)
            .where(
                ChargingSession.settlement_reason == "debited",
                or_(
                    Invoice.driver_id == wallet.driver_id,
                    ChargingSession.driver_id == wallet.driver_id,
                    related_entry,
                ),
            )
        )
    ).all()
    for invoice, charging in invoices:
        if invoice.driver_id != charging.driver_id:
            issues.add("invoice_driver_mismatch")
        entries = (
            await session.scalars(
                select(WalletLedger).where(
                    WalletLedger.reference_id.in_([str(charging.id), str(invoice.id)]),
                    or_(
                        WalletLedger.entry_type == "charging_debit",
                        WalletLedger.reference_type == "charging_session",
                    ),
                )
            )
        ).all()
        if len(entries) != 1:
            issues.add("invoice_debit_count")
        for entry in entries:
            expected_wallet = await session.scalar(
                select(Wallet.id).where(Wallet.driver_id == invoice.driver_id)
            )
            if entry.wallet_id != expected_wallet:
                issues.add("invoice_debit_wallet")
            if entry.entry_type != "charging_debit":
                issues.add("invoice_debit_type")
            if entry.reference_type != "charging_session" or entry.reference_id != str(
                charging.id
            ):
                issues.add("invoice_debit_reference")
            if entry.amount_vnd != -invoice.total_vnd or invoice.total_vnd == 0:
                issues.add("invoice_debit_amount")
    return total, sorted(issues)


async def doi_chieu_so_du(
    session: AsyncSession, *, wallet_id: UUID | None = None
) -> list[UUID]:
    """Lock inconsistent wallets once, with audit in the caller's transaction.

    SKIP LOCKED makes concurrent writers and reconcilers safe. Returning newly
    locked IDs lets the runner emit warnings only after a successful commit.
    """
    query = select(Wallet.id).order_by(Wallet.id)
    if wallet_id is not None:
        query = query.where(Wallet.id == wallet_id)
    locked = []
    for identifier in (await session.scalars(query)).all():
        wallet = await session.scalar(
            select(Wallet)
            .where(Wallet.id == identifier)
            .with_for_update(skip_locked=True)
            .execution_options(populate_existing=True)
        )
        if wallet is None:
            continue
        total, issues = await wallet_issues(session, wallet)
        if not issues or wallet.status == "locked":
            continue
        async with session.begin_nested():
            wallet.status = "locked"
            await ghi_nhat_ky(
                session,
                actor_id=None,
                action="wallet.reconciliation_locked",
                object_type="wallet",
                object_id=str(wallet.id),
                data={
                    "reasons": issues,
                    "balance_vnd": wallet.balance_vnd,
                    "ledger_total_vnd": total,
                },
            )
        locked.append(wallet.id)
    return locked


async def run_reconciliation() -> int:
    """Bound lock lifetime to one wallet; scan IDs in batches."""
    cursor = None
    changed = 0
    while True:
        async with SessionFactory() as session:
            query = select(Wallet.id).order_by(Wallet.id).limit(500)
            if cursor is not None:
                query = query.where(Wallet.id > cursor)
            identifiers = (await session.scalars(query)).all()
        if not identifiers:
            return changed
        for identifier in identifiers:
            try:
                async with SessionFactory() as session, session.begin():
                    locked = await doi_chieu_so_du(session, wallet_id=identifier)
                for locked_id in locked:
                    logger.warning(
                        "wallet_reconciliation_locked wallet_id=%s", locked_id
                    )
                changed += len(locked)
            except (SQLAlchemyError, ValueError):
                logger.error("wallet_reconciliation_failed wallet_id=%s", identifier)
        cursor = identifiers[-1]


async def reconciliation_loop() -> None:
    while True:
        await asyncio.sleep(settings.wallet_reconciliation_interval_seconds)
        try:
            await run_reconciliation()
        except SQLAlchemyError:
            logger.error("wallet_reconciliation_scan_failed")
