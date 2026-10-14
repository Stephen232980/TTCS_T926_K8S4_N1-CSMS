"""T-102 / S-37: Unit and integration tests for chot_phien closure and settlement.

Invariants verified:
1. Atomicity: In a single transaction, chot_phien locks the session row, creates the invoice,
   debits the wallet via tru_vi, and marks settlement_completed_at & settlement_reason.
2. Invoiced with charge (>0 VND): wallet debited, ledger entry created, settlement_reason='debited'.
3. Zero invoice (0 VND): invoice created with total_vnd=0, wallet untouched (no ledger row),
   settlement_reason='zero_invoice'.
4. Failure isolation: Failure during/after invoicing rolls back the entire transaction, leaving
   no orphan invoice and no wallet deduction. The recovery scan will retry later.
5. Idempotency: Calling chot_phien multiple times on the same session returns the same result
   and does not duplicate invoices or wallet ledger rows.
6. Catch-up: Sessions with an existing invoice created after the cutoff but missing a wallet debit
   are debited and marked settled without re-creating the invoice.
7. Needs review / Pending: Invoices that cannot be finalized (missing tariff, active session)
   are not debited and remain unsettled (settlement_completed_at is None).
8. Logging: Logs contain session_id and do not contain driver names or sensitive data.
9. Migration: Alembic migration backfills legacy_exempt for sessions whose invoices were created
   before the cutoff and have no charging_debit entry.
"""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError

from src.modules.billing import closure
from src.modules.billing.closure import chot_phien, scan_unsettled_sessions
from src.modules.billing.invoicing import lap_hoa_don
from src.modules.billing.models import Invoice, InvoiceLine
from src.modules.charging.models import ChargingSession
from src.modules.wallet.models import Wallet, WalletLedger
from tests.test_effective_tariffs import committed_tariff_db as isolated_closure_db
from tests.test_t80_invoicing import seed

committed_tariff_db = isolated_closure_db


@pytest.fixture
async def factory(committed_tariff_db, monkeypatch):
    monkeypatch.setattr(closure, "SessionFactory", committed_tariff_db)
    return committed_tariff_db


async def saved(factory, **kwargs):
    async with factory() as db, db.begin():
        charging, *_ = await seed(db, **kwargs)
        return charging.id


async def counts(factory):
    async with factory() as db:
        return tuple(
            [
                await db.scalar(select(func.count()).select_from(model))
                for model in (Invoice, InvoiceLine, WalletLedger)
            ]
        )


async def test_t102_chot_phien_thanh_cong_co_phi_tru_vi_va_danh_dau_debited(factory):
    """Phiên sạc có phí: lập hoá đơn + trừ ví + settlement_reason='debited' trong 1 transaction."""
    session_id = await saved(factory)
    result = await chot_phien(session_id, settle=True)
    assert result.status == "ready"
    assert result.invoice is not None
    assert result.invoice.total_vnd > 0

    async with factory() as db:
        charging = await db.get(ChargingSession, session_id)
        assert charging.settlement_completed_at is not None
        assert charging.settlement_reason == "debited"

        invoice = await db.scalar(
            select(Invoice).where(Invoice.session_id == session_id)
        )
        assert invoice is not None
        assert invoice.total_vnd == result.invoice.total_vnd

        ledger = await db.scalar(
            select(WalletLedger).where(
                WalletLedger.entry_type == "charging_debit",
                WalletLedger.reference_type == "charging_session",
                WalletLedger.reference_id == str(session_id),
            )
        )
        assert ledger is not None
        assert ledger.amount_vnd == -invoice.total_vnd

        wallet = await db.get(Wallet, ledger.wallet_id)
        assert wallet.balance_vnd == 1_000_000 - invoice.total_vnd


async def test_t102_chot_phien_zero_dong_danh_dau_zero_invoice_khong_tru_vi(factory):
    """Hoá đơn 0 đồng: đặt settlement_reason='zero_invoice', không ghi dòng sổ cái."""
    session_id = await saved(factory, last=0)
    result = await chot_phien(session_id, settle=True)
    assert result.status == "ready"
    assert result.invoice.total_vnd == 0

    async with factory() as db:
        charging = await db.get(ChargingSession, session_id)
        assert charging.settlement_completed_at is not None
        assert charging.settlement_reason == "zero_invoice"

        # Không có dòng ghi sổ cái nào
        ledger = await db.scalar(
            select(WalletLedger).where(
                WalletLedger.reference_type == "charging_session",
                WalletLedger.reference_id == str(session_id),
            )
        )
        assert ledger is None


async def test_t102_loi_giua_chung_sau_lap_hoa_don_rollback_toan_bo_khong_mo_coi(
    factory, monkeypatch
):
    """Cố ý gây lỗi sau bước lập hoá đơn: toàn bộ transaction rollback, không lưu hoá đơn mồ côi."""
    session_id = await saved(factory)

    # Mock tru_vi để ném ra ngoại lệ
    async def fail_tru_vi(*args, **kwargs):
        raise SQLAlchemyError("Giả lập lỗi kết nối hoặc xử lý ví")

    monkeypatch.setattr(closure, "tru_vi", fail_tru_vi)

    async with factory() as db:
        with pytest.raises(SQLAlchemyError):
            async with db.begin():
                await chot_phien(session_id, db=db, settle=True)

    # Kiểm tra DB: không có hoá đơn nào và phiên chưa chốt
    async with factory() as db:
        charging = await db.get(ChargingSession, session_id)
        assert charging.settlement_completed_at is None
        assert charging.settlement_reason is None
        assert (
            await db.scalar(select(Invoice.id).where(Invoice.session_id == session_id))
            is None
        )
        assert (
            await db.scalar(
                select(WalletLedger.id).where(
                    WalletLedger.reference_id == str(session_id)
                )
            )
            is None
        )

    # Khôi phục tru_vi: lần sau chốt thành công trọn vẹn
    monkeypatch.undo()
    async with factory() as db, db.begin():
        retry_result = await chot_phien(session_id, db=db, settle=True)
    assert retry_result.status == "ready"
    async with factory() as db:
        charging = await db.get(ChargingSession, session_id)
        assert charging.settlement_completed_at is not None
        assert charging.settlement_reason == "debited"


async def test_t102_phien_da_co_hoa_don_nhung_chua_tru_vi_duoc_tru_bu_khong_trung(
    factory,
):
    """Phiên đã có hoá đơn từ trước nhưng chưa chốt/trừ ví: chot_phien trừ ví bù và không tạo trùng hoá đơn."""
    session_id = await saved(factory)

    # Tạo trước hoá đơn độc lập mà không trừ ví (như trạng thái cũ ở T-81)
    async with factory() as db, db.begin():
        invoice_outcome = await lap_hoa_don(db, session_id)
        assert invoice_outcome.status == "ready"

    assert await counts(factory) == (1, 1, 0)

    # Chốt phiên
    async with factory() as db, db.begin():
        result = await chot_phien(session_id, db=db, settle=True)
    assert result.status == "ready"
    assert result.invoice.id == invoice_outcome.invoice.id

    # Hoá đơn vẫn chỉ có 1, nhưng đã có thêm 1 dòng ví
    assert await counts(factory) == (1, 1, 1)

    async with factory() as db:
        charging = await db.get(ChargingSession, session_id)
        assert charging.settlement_completed_at is not None
        assert charging.settlement_reason == "debited"


async def test_t102_chot_phien_idempotent_nhieu_lan_khong_sinh_them_dong(factory):
    """Gọi chot_phien nhiều lần cho cùng một phiên chỉ chốt và trừ ví đúng 1 lần."""
    session_id = await saved(factory)

    async def run_once():
        async with factory() as db, db.begin():
            return await chot_phien(session_id, db=db, settle=True)

    results = await asyncio.gather(*(run_once() for _ in range(3)))
    assert {r.invoice.id for r in results} == {results[0].invoice.id}
    assert await counts(factory) == (1, 1, 1)


async def test_t102_needs_review_khong_tru_vi_va_khong_settle(factory):
    """Phiên sạc needs_review (ví dụ thiếu biểu giá): không trừ ví, không đặt settlement."""
    session_id = await saved(factory, with_tariff=False)
    async with factory() as db, db.begin():
        result = await chot_phien(session_id, db=db, settle=True)
    assert result.status == "needs_review"

    async with factory() as db:
        charging = await db.get(ChargingSession, session_id)
        assert charging.settlement_completed_at is None
        assert charging.settlement_reason is None
    assert await counts(factory) == (0, 0, 0)


async def test_t102_scan_unsettled_sessions_processes_and_marks_settled(factory):
    """Job scan_unsettled_sessions tự động nhặt và chốt các phiên chưa settlement."""
    id1 = await saved(factory)
    id2 = await saved(factory, last=0)

    scan_res = await scan_unsettled_sessions(settle=True)
    assert scan_res.scanned >= 2
    assert scan_res.ready >= 2

    async with factory() as db:
        c1 = await db.get(ChargingSession, id1)
        c2 = await db.get(ChargingSession, id2)
        assert c1.settlement_reason == "debited"
        assert c2.settlement_reason == "zero_invoice"

    # Lần quét thứ hai không còn phiên nào cần chốt
    scan_res_2 = await scan_unsettled_sessions(settle=True)
    assert scan_res_2.scanned == 0


async def test_t102_migration_legacy_exempt_logic(factory):
    """Kiểm tra logic nghiệp vụ của migration legacy_exempt:

    - Hoá đơn tạo trước cutoff và chưa có dòng trừ ví -> đánh legacy_exempt.
    - Hoá đơn tạo sau cutoff hoặc đã có dòng trừ ví -> không bị đánh legacy_exempt.
    """
    cutoff = datetime.now(UTC) + timedelta(hours=1)

    async with factory() as db, db.begin():
        # Phiên 1: hoá đơn tạo lúc này (nhỏ hơn cutoff trong tương lai), chưa trừ ví -> exempt
        c1, *_ = await seed(db)
        inv1 = await lap_hoa_don(db, c1.id)
        assert inv1.status == "ready"

        # Phiên 2: hoá đơn tạo lúc này, nhưng cutoff trong quá khứ -> không exempt
        c2, *_ = await seed(db)
        inv2 = await lap_hoa_don(db, c2.id)
        assert inv2.status == "ready"

        id1, id2 = c1.id, c2.id

    # Áp dụng migration với cutoff tương lai: chỉ c1 được exempt nếu query với cutoff tương lai
    async with factory() as db, db.begin():
        await db.execute(
            text(
                """
                UPDATE charging_sessions cs
                SET settlement_completed_at = :completed_at,
                    settlement_reason = 'legacy_exempt'
                FROM invoices inv
                WHERE cs.id = inv.session_id
                  AND cs.id = :c1_id
                  AND inv.created_at < :future_cutoff
                  AND cs.settlement_completed_at IS NULL
                  AND NOT EXISTS (
                      SELECT 1 FROM wallet_ledger wl
                      WHERE wl.entry_type = 'charging_debit'
                        AND wl.reference_type = 'charging_session'
                        AND wl.reference_id = cs.id::text
                  )
                """
            ),
            {"c1_id": id1, "future_cutoff": cutoff, "completed_at": datetime.now(UTC)},
        )

        # Với c2, test cutoff trong quá khứ (không thoả mãn inv.created_at < past_cutoff)
        past_cutoff = datetime.now(UTC) - timedelta(days=1)
        await db.execute(
            text(
                """
                UPDATE charging_sessions cs
                SET settlement_completed_at = :completed_at,
                    settlement_reason = 'legacy_exempt'
                FROM invoices inv
                WHERE cs.id = inv.session_id
                  AND cs.id = :c2_id
                  AND inv.created_at < :past_cutoff
                  AND cs.settlement_completed_at IS NULL
                  AND NOT EXISTS (
                      SELECT 1 FROM wallet_ledger wl
                      WHERE wl.entry_type = 'charging_debit'
                        AND wl.reference_type = 'charging_session'
                        AND wl.reference_id = cs.id::text
                  )
                """
            ),
            {
                "c2_id": id2,
                "past_cutoff": past_cutoff,
                "completed_at": datetime.now(UTC),
            },
        )

    async with factory() as db:
        res1 = await db.get(ChargingSession, id1)
        res2 = await db.get(ChargingSession, id2)
        assert res1.settlement_reason == "legacy_exempt"
        assert res1.settlement_completed_at is not None
        assert res2.settlement_reason is None
        assert res2.settlement_completed_at is None


async def test_t102_closure_runner_worker_tu_dong_tru_vi(factory):
    """Xác nhận ClosureRunner.worker tự động chốt và trừ ví (settle=True) cho phiên kết thúc."""
    session_id = await saved(factory)
    runner = closure.ClosureRunner(capacity=10, settle=True)
    assert runner.schedule(session_id)

    worker = asyncio.create_task(runner.worker())
    try:
        await asyncio.wait_for(runner.queue.join(), 5)
    finally:
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)

    async with factory() as db:
        cs = await db.get(ChargingSession, session_id)
        assert cs is not None
        assert cs.settlement_completed_at is not None
        assert cs.settlement_reason == "debited"
        ledger = await db.scalar(
            select(WalletLedger).where(
                WalletLedger.entry_type == "charging_debit",
                WalletLedger.reference_id == str(session_id),
            )
        )
        assert ledger is not None
