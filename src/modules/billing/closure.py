"""T-81: post-reply invoice closure and durable database recovery scan."""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.modules.billing.invoicing import InvoiceResult, lap_hoa_don
from src.modules.charging.models import ChargingSession
from src.modules.wallet.service import tru_vi
from src.platform.database.session import SessionFactory

logger = logging.getLogger("csms.billing")


async def _chot_phien_in_session(
    db: AsyncSession, session_id: int, *, settle: bool = False
) -> InvoiceResult:
    """Execute lap_hoa_don, and when settle=True, tru_vi and mark settlement.

    Lock the session row (with_for_update) to prevent concurrent settlement races.
    If already settled, return idempotent success.
    If lap_hoa_don yields needs_review or pending, return without debiting wallet.
    When ready and settle=True, debit wallet via tru_vi and record settlement fields atomically.
    """
    charging = await db.scalar(
        select(ChargingSession)
        .where(ChargingSession.id == session_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if charging is None:
        return await lap_hoa_don(db, session_id)

    if charging.settlement_completed_at is not None:
        return await lap_hoa_don(db, session_id)

    outcome = await lap_hoa_don(db, session_id)
    if outcome.status != "ready" or outcome.invoice is None:
        return outcome

    if not settle:
        return outcome

    invoice = outcome.invoice
    await tru_vi(db, invoice=invoice)

    now = datetime.now(UTC)
    charging.settlement_completed_at = now
    charging.settlement_reason = "zero_invoice" if invoice.total_vnd == 0 else "debited"
    await db.flush()
    logger.info(
        "charging_session_settled session=%s reason=%s total_vnd=%s",
        session_id,
        charging.settlement_reason,
        invoice.total_vnd,
    )
    return outcome


async def chot_phien(
    session_id: int, *, db: AsyncSession | None = None, settle: bool = False
) -> InvoiceResult:
    """Own one transaction, or join the supplied caller transaction.

    In a single transaction:
    1. Lock session row with FOR UPDATE.
    2. Generate/fetch invoice via lap_hoa_don.
    3. If settle=True (T-102): debit wallet via tru_vi and mark settlement.
    4. Set settlement_completed_at and settlement_reason ('debited' or 'zero_invoice').
    Any failure rolls back all changes atomically; the recovery scan will retry later.
    """
    if db is not None:
        return await _chot_phien_in_session(db, session_id, settle=settle)
    async with SessionFactory() as session, session.begin():
        return await _chot_phien_in_session(session, session_id, settle=settle)


@dataclass
class ScanResult:
    scanned: int = 0
    ready: int = 0
    needs_review: int = 0
    pending: int = 0
    busy: int = 0
    failed: int = 0


async def scan_unsettled_sessions(
    *, batch_size: int = 100, settle: bool = False
) -> ScanResult:
    """Keyset pages include saved invoices and manually closed sessions.

    Process each candidate in its own transaction; skip a busy row and retry on
    the next scan. Never use 'no invoice' as the completion predicate.
    """
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    result = ScanResult()
    cursor = 0
    while True:
        async with SessionFactory() as db:
            identifiers = list(
                await db.scalars(
                    select(ChargingSession.id)
                    .where(
                        ChargingSession.id > cursor,
                        ChargingSession.ended_at.is_not(None),
                        ChargingSession.settlement_completed_at.is_(None),
                    )
                    .order_by(ChargingSession.id)
                    .limit(batch_size)
                )
            )
        if not identifiers:
            return result
        cursor = identifiers[-1]
        for session_id in identifiers:
            result.scanned += 1
            try:
                async with SessionFactory() as db, db.begin():
                    locked = await db.scalar(
                        select(ChargingSession.id)
                        .where(
                            ChargingSession.id == session_id,
                            ChargingSession.ended_at.is_not(None),
                            ChargingSession.settlement_completed_at.is_(None),
                        )
                        .with_for_update(skip_locked=True)
                    )
                    if locked is None:
                        result.busy += 1
                        continue
                    outcome = await chot_phien(session_id, db=db, settle=settle)
                if outcome.status == "ready":
                    result.ready += 1
                elif outcome.status == "needs_review":
                    result.needs_review += 1
                else:
                    result.pending += 1
            except Exception:  # noqa: BLE001 - isolate failures; DB remains retryable.
                result.failed += 1
                logger.error("charging_closure_failed session=%s", session_id)


async def closure_scan_loop() -> None:
    while True:
        try:
            await scan_unsettled_sessions()
        except Exception:  # noqa: BLE001 - supervise recovery without logging SQL data.
            logger.error("charging_closure_scan_failed")
        await asyncio.sleep(settings.charging_closure_scan_interval_seconds)


class ClosureRunner:
    """A bounded hint queue; the persisted ended session is the recovery source."""

    def __init__(self, capacity: int = 256) -> None:
        self.queue: asyncio.Queue[int] = asyncio.Queue(maxsize=capacity)
        self.pending: set[int] = set()

    def schedule(self, session_id: int) -> bool:
        if session_id in self.pending:
            return True
        try:
            self.queue.put_nowait(session_id)
        except asyncio.QueueFull:
            return False
        self.pending.add(session_id)
        return True

    async def worker(self) -> None:
        while True:
            session_id = await self.queue.get()
            try:
                await chot_phien(session_id)
            except Exception:  # noqa: BLE001 - keep workers alive for later sessions.
                logger.error("charging_closure_failed session=%s", session_id)
            finally:
                self.pending.discard(session_id)
                self.queue.task_done()


_runner: ClosureRunner | None = None


def schedule_closure(session_id: int) -> bool:
    """Nonblocking; lack of a runner/full queue leaves the DB scan as fallback."""
    return _runner.schedule(session_id) if _runner is not None else False


@asynccontextmanager
async def closure_lifespan() -> AsyncIterator[None]:
    global _runner
    runner = ClosureRunner()
    _runner = runner
    tasks = [asyncio.create_task(runner.worker()) for _ in range(2)]
    tasks.append(asyncio.create_task(closure_scan_loop()))
    try:
        yield
    finally:
        _runner = None
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
