"""Tests for T-101: tru_vi wallet debit function under Story S-37.

Invariants verified:
1. Debit wallet according to invoice in caller's transaction.
2. Negative amount equal to -invoice.total_vnd with entry_type='charging_debit'.
3. Reference is charging session ID (reference_type='charging_session', reference_id=str(session_id)).
4. Unique reference prevents double debiting (idempotent replay returns same row).
5. Insufficient funds still debited, negative balance represents debt.
6. Zero invoice (0 VND) skipped, no ledger entry, returns None.
7. settlement_* fields on charging_sessions remain untouched (reserved for T-102).
8. Caller transaction ownership: rolling back caller transaction rolls back ledger & balance.
9. Locked wallet rejected with WalletLockedError.
10. Auto-provisions wallet if driver does not have one yet.
11. Query via session_id lookup.
12. Full reconciliation compatibility with doi_chieu_so_du / wallet_issues.
"""

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text

from src.modules.billing.models import Invoice
from src.modules.charging.models import ChargingSession
from src.modules.identity.models import Role, User, UserRole
from src.modules.stations.models import Connector
from src.modules.wallet.exceptions import (
    WalletAmountError,
    WalletLockedError,
    WalletNotFoundError,
    WalletOwnershipError,
)
from src.modules.wallet.models import Wallet, WalletLedger
from src.modules.wallet.provisioning import ensure_driver_wallet
from src.modules.wallet.reconciliation import wallet_issues
from src.modules.wallet.service import ghi_so_cai, tru_vi
from tests import test_wallet_service
from tests.test_ocpp_foundation import charger_fixture

isolated_wallet_db = test_wallet_service.isolated_wallet_db

STAMP = datetime(2026, 10, 11, 10, 0, tzinfo=UTC)


async def setup(session):
    """Create a driver with no wallet; provisioning is exercised explicitly."""
    station, charger = await charger_fixture(session)
    connector = Connector(
        charge_point_id=charger.id, connector_number=1, status="Available"
    )
    driver = User(email=f"t101-{uuid4()}@example.com", password_hash="unused")
    role = await session.scalar(select(Role).where(Role.code == "driver"))
    if role is None:
        role = Role(code="driver")
        session.add(role)
    session.add_all([connector, driver])
    await session.flush()
    session.add(UserRole(user_id=driver.id, role_id=role.id))
    await session.flush()
    return station, charger, connector, driver


async def create_fixture(
    session, *, initial_balance: int = 100_000, wallet_status: str = "active"
):
    """Create station, charge point, connector, driver, wallet, charging session, and invoice."""
    station, charger, connector, driver, *_ = await setup(session)

    # Ensure driver wallet
    wallet = await session.scalar(select(Wallet).where(Wallet.driver_id == driver.id))
    if wallet is None:
        wallet = await ensure_driver_wallet(session, driver.id)
    if initial_balance != 0:
        await ghi_so_cai(
            session,
            wallet_id=wallet.id,
            entry_type="manual_topup",
            amount_vnd=initial_balance,
            reference_type="test",
            reference_id=str(uuid4()),
        )
    if wallet_status != "active":
        wallet.status = wallet_status
    await session.flush()

    charging = ChargingSession(
        charge_point_id=charger.id,
        connector_id=connector.id,
        driver_id=driver.id,
        tag_tail="ABCD",
        authorization_status="Accepted",
        started_at=STAMP,
        ended_at=STAMP + timedelta(hours=1),
        meter_start_wh=Decimal(0),
        meter_stop_wh=Decimal(10_000),
        review_reasons=[],
        billing_lifecycle_version=0,
        settlement_completed_at=None,
        settlement_reason=None,
    )
    session.add(charging)
    await session.flush()

    return station, charger, connector, driver, wallet, charging


def make_invoice(charging, station, driver, *, total_vnd: int) -> Invoice:
    return Invoice(
        session_id=charging.id,
        driver_id=driver.id,
        station_id=station.id,
        total_vnd=total_vnd,
        rounding_rule="half_up",
    )


@pytest.mark.asyncio
async def test_tru_vi_thanh_cong_va_ghi_so_cai(db_session):
    """Trừ ví thành công khi có đủ tiền: ghi sổ cái âm, số dư giảm, reference là mã phiên."""
    station, _, _, driver, wallet, charging = await create_fixture(
        db_session, initial_balance=100_000
    )
    invoice = make_invoice(charging, station, driver, total_vnd=35_000)
    db_session.add(invoice)
    await db_session.flush()

    ledger = await tru_vi(db_session, invoice=invoice)

    assert ledger is not None
    assert ledger.wallet_id == wallet.id
    assert ledger.entry_type == "charging_debit"
    assert ledger.amount_vnd == -35_000
    assert ledger.balance_after_vnd == 65_000
    assert ledger.reference_type == "charging_session"
    assert ledger.reference_id == str(charging.id)

    # Số dư ví trên database đồng bộ với balance_after
    await db_session.refresh(wallet)
    assert wallet.balance_vnd == 65_000


@pytest.mark.asyncio
async def test_tru_vi_thieu_tien_van_tru_de_so_du_am(db_session):
    """Ví thiếu tiền (kể cả 0đ hoặc âm sẵn) vẫn trừ bình thường, số dư âm là nợ."""
    # Case A: Số dư 10.000 đ, hoá đơn 50.000 đ -> số dư âm -40.000 đ
    station, _, _, driver, wallet, charging = await create_fixture(
        db_session, initial_balance=10_000
    )
    invoice = make_invoice(charging, station, driver, total_vnd=50_000)
    db_session.add(invoice)
    await db_session.flush()

    ledger = await tru_vi(db_session, invoice=invoice)

    assert ledger is not None
    assert ledger.amount_vnd == -50_000
    assert ledger.balance_after_vnd == -40_000
    await db_session.refresh(wallet)
    assert wallet.balance_vnd == -40_000

    # Case B: Tiếp tục phiên thứ 2 từ số dư âm -40.000 đ, hoá đơn 20.000 đ -> -60.000 đ
    charging2 = ChargingSession(
        charge_point_id=charging.charge_point_id,
        connector_id=charging.connector_id,
        driver_id=driver.id,
        tag_tail="ABCD",
        authorization_status="Accepted",
        started_at=STAMP + timedelta(hours=2),
        ended_at=STAMP + timedelta(hours=3),
        meter_start_wh=Decimal(10_000),
        meter_stop_wh=Decimal(15_000),
        review_reasons=[],
        billing_lifecycle_version=0,
    )
    db_session.add(charging2)
    await db_session.flush()

    invoice2 = make_invoice(charging2, station, driver, total_vnd=20_000)
    db_session.add(invoice2)
    await db_session.flush()

    ledger2 = await tru_vi(db_session, invoice=invoice2)
    assert ledger2 is not None
    assert ledger2.amount_vnd == -20_000
    assert ledger2.balance_after_vnd == -60_000
    await db_session.refresh(wallet)
    assert wallet.balance_vnd == -60_000


@pytest.mark.asyncio
async def test_tru_vi_hoa_don_zero_dong_bo_qua_khong_ghi_dong(db_session):
    """Hoá đơn 0 đồng thì bỏ qua hoàn toàn, không ghi dòng vào sổ cái, trả về None."""
    station, _, _, driver, wallet, charging = await create_fixture(
        db_session, initial_balance=50_000
    )
    invoice = make_invoice(charging, station, driver, total_vnd=0)
    db_session.add(invoice)
    await db_session.flush()

    result = await tru_vi(db_session, invoice=invoice)

    assert result is None
    await db_session.refresh(wallet)
    assert wallet.balance_vnd == 50_000

    # Kiểm tra tuyệt đối không có dòng sổ cái nào sinh ra cho phiên này
    entries = (
        await db_session.scalars(
            select(WalletLedger).where(
                WalletLedger.wallet_id == wallet.id,
                WalletLedger.reference_id == str(charging.id),
            )
        )
    ).all()
    assert len(entries) == 0


@pytest.mark.asyncio
async def test_tru_vi_hai_lan_cho_cung_phien_idempotent_chan_tru_trung(db_session):
    """Gọi tru_vi hai lần cho cùng một phiên sạc: unique constraint chặn trừ lặp, trả về bản ghi cũ."""
    station, _, _, driver, wallet, charging = await create_fixture(
        db_session, initial_balance=100_000
    )
    invoice = make_invoice(charging, station, driver, total_vnd=40_000)
    db_session.add(invoice)
    await db_session.flush()

    first = await tru_vi(db_session, invoice=invoice)
    assert first is not None
    assert first.balance_after_vnd == 60_000

    # Gọi lại lần thứ hai
    second = await tru_vi(db_session, invoice=invoice)
    assert second is not None
    assert second.id == first.id
    assert second.balance_after_vnd == 60_000

    # Số dư ví vẫn là 60.000 đ, không bị trừ thành 20.000 đ
    await db_session.refresh(wallet)
    assert wallet.balance_vnd == 60_000

    # Kiểm tra chỉ có duy nhất 1 bản ghi sổ cái cho phiên này
    entries = (
        await db_session.scalars(
            select(WalletLedger).where(
                WalletLedger.wallet_id == wallet.id,
                WalletLedger.reference_id == str(charging.id),
            )
        )
    ).all()
    assert len(entries) == 1


@pytest.mark.asyncio
async def test_tru_vi_khong_dat_settlement_fields(db_session):
    """Hàm tru_vi tuyệt đối không cập nhật các trường settlement_* trên charging_sessions."""
    station, _, _, driver, _, charging = await create_fixture(
        db_session, initial_balance=100_000
    )
    assert charging.settlement_completed_at is None
    assert charging.settlement_reason is None

    invoice = make_invoice(charging, station, driver, total_vnd=30_000)
    db_session.add(invoice)
    await db_session.flush()

    await tru_vi(db_session, invoice=invoice)

    # Re-fetch charging session từ database
    refreshed = await db_session.scalar(
        select(ChargingSession).where(ChargingSession.id == charging.id)
    )
    assert refreshed is not None
    assert refreshed.settlement_completed_at is None
    assert refreshed.settlement_reason is None


@pytest.mark.asyncio
async def test_tru_vi_trong_giao_dich_caller_rollback_sach(db_session):
    """Hàm tru_vi chạy trong giao dịch caller; caller rollback thì số dư và sổ cái phục hồi sạch."""
    station, _, _, driver, wallet, charging = await create_fixture(
        db_session, initial_balance=50_000
    )
    invoice = make_invoice(charging, station, driver, total_vnd=20_000)
    db_session.add(invoice)
    await db_session.flush()

    # Mở một savepoint mô phỏng transaction nhánh của caller
    charging_id = charging.id
    savepoint = await db_session.begin_nested()
    try:
        await tru_vi(db_session, invoice=invoice)
        # Trong transaction: số dư là 30.000 đ
        assert wallet.balance_vnd == 30_000
        # Cố ý rollback savepoint
    finally:
        await savepoint.rollback()

    # Sau rollback: số dư phục hồi về 50.000 đ và không có dòng sổ cái
    await db_session.refresh(wallet)
    assert wallet.balance_vnd == 50_000

    entry = await db_session.scalar(
        select(WalletLedger).where(
            WalletLedger.reference_id == str(charging_id),
            WalletLedger.entry_type == "charging_debit",
        )
    )
    assert entry is None


@pytest.mark.asyncio
async def test_tru_vi_tu_choi_khi_vi_bi_khoa(db_session):
    """Ví ở trạng thái locked phải bị từ chối với WalletLockedError."""
    station, _, _, driver, wallet, charging = await create_fixture(
        db_session, initial_balance=50_000, wallet_status="locked"
    )
    invoice = make_invoice(charging, station, driver, total_vnd=20_000)
    db_session.add(invoice)
    await db_session.flush()

    with pytest.raises(WalletLockedError):
        await tru_vi(db_session, invoice=invoice)

    await db_session.refresh(wallet)
    assert wallet.balance_vnd == 50_000


@pytest.mark.asyncio
async def test_tru_vi_tu_dong_tao_vi_khi_tai_xe_chua_co_vi(db_session):
    """Tài xế có vai trò driver nhưng chưa có ví -> tru_vi tự động ensure_driver_wallet rồi trừ."""
    station, charger, connector, driver, *_ = await setup(db_session)

    # Đảm bảo chưa có ví
    existing_wallet = await db_session.scalar(
        select(Wallet).where(Wallet.driver_id == driver.id)
    )
    assert existing_wallet is None

    charging = ChargingSession(
        charge_point_id=charger.id,
        connector_id=connector.id,
        driver_id=driver.id,
        tag_tail="ABCD",
        authorization_status="Accepted",
        started_at=STAMP,
        ended_at=STAMP + timedelta(hours=1),
        meter_start_wh=Decimal(0),
        meter_stop_wh=Decimal(5_000),
        review_reasons=[],
        billing_lifecycle_version=0,
    )
    db_session.add(charging)
    await db_session.flush()

    invoice = make_invoice(charging, station, driver, total_vnd=15_000)
    db_session.add(invoice)
    await db_session.flush()

    ledger = await tru_vi(db_session, invoice=invoice)
    assert ledger is not None
    assert ledger.amount_vnd == -15_000
    assert ledger.balance_after_vnd == -15_000

    created_wallet = await db_session.scalar(
        select(Wallet).where(Wallet.driver_id == driver.id)
    )
    assert created_wallet is not None
    assert created_wallet.balance_vnd == -15_000


@pytest.mark.asyncio
async def test_tru_vi_tra_cuu_qua_session_id(db_session):
    """Gọi tru_vi chỉ với session_id: tự tìm hoá đơn đã lưu trong DB và trừ ví."""
    station, _, _, driver, wallet, charging = await create_fixture(
        db_session, initial_balance=80_000
    )
    invoice = make_invoice(charging, station, driver, total_vnd=30_000)
    db_session.add(invoice)
    await db_session.flush()

    ledger = await tru_vi(db_session, session_id=charging.id)
    assert ledger is not None
    assert ledger.amount_vnd == -30_000
    assert ledger.balance_after_vnd == 50_000

    await db_session.refresh(wallet)
    assert wallet.balance_vnd == 50_000


@pytest.mark.asyncio
async def test_tru_vi_tham_so_hop_le_va_ngoai_le(db_session):
    """Kiểm tra xử lý ngoại lệ đầu vào của hàm tru_vi."""
    # 1. Không truyền invoice lẫn session_id -> ValueError
    with pytest.raises(ValueError, match="Cần cung cấp invoice hoặc session_id"):
        await tru_vi(db_session)

    # 2. Truyền session_id không tồn tại trong bảng invoices -> LookupError
    with pytest.raises(LookupError, match="Không tìm thấy hoá đơn"):
        await tru_vi(db_session, session_id=999_999_999)

    # 3. Hoá đơn có total_vnd < 0 -> WalletAmountError
    station, _, _, driver, _, charging = await create_fixture(db_session)
    invalid_invoice = Invoice(
        session_id=charging.id,
        driver_id=driver.id,
        station_id=station.id,
        total_vnd=-1000,
        rounding_rule="half_up",
    )
    with pytest.raises(WalletAmountError, match="Tổng tiền hoá đơn không được âm"):
        await tru_vi(db_session, invoice=invalid_invoice)


@pytest.mark.asyncio
async def test_tru_vi_tuong_thich_reconciliation_doi_chieu(db_session):
    """Dòng trừ ví của tru_vi hoàn toàn hợp lệ với cơ chế kiểm tra đối chiếu sổ cái (wallet_issues)."""
    station, _, _, driver, wallet, charging = await create_fixture(
        db_session, initial_balance=100_000
    )
    invoice = make_invoice(charging, station, driver, total_vnd=45_000)
    db_session.add(invoice)
    await db_session.flush()

    # Trừ ví
    await tru_vi(db_session, invoice=invoice)

    # Giả định sau khi chốt phiên (T-102), charging_session đánh dấu settlement_reason = 'debited'
    charging.settlement_reason = "debited"
    charging.settlement_completed_at = STAMP + timedelta(hours=1)
    await db_session.flush()

    # Chạy kiểm tra đối chiếu sổ cái
    total, issues = await wallet_issues(db_session, wallet)
    assert total == 55_000
    assert issues == []


@pytest.mark.asyncio
async def test_explicit_wallet_must_belong_to_invoice_driver(db_session):
    station, _, _, driver, owner, charging = await create_fixture(db_session)
    _, _, _, _, other, _ = await create_fixture(db_session)
    invoice = make_invoice(charging, station, driver, total_vnd=35_000)
    db_session.add(invoice)
    await db_session.flush()

    with pytest.raises(WalletOwnershipError):
        await tru_vi(db_session, invoice=invoice, wallet_id=other.id)
    for wallet in (owner, other):
        await db_session.refresh(wallet)
        assert wallet.balance_vnd == 100_000
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(WalletLedger)
            .where(WalletLedger.entry_type == "charging_debit")
            .where(WalletLedger.wallet_id.in_([owner.id, other.id]))
        )
        == 0
    )

    with pytest.raises(WalletNotFoundError):
        await tru_vi(db_session, invoice=invoice, wallet_id=uuid4())
    # The caller transaction remains usable after both domain errors.
    entry = await tru_vi(db_session, invoice=invoice, wallet_id=owner.id)
    assert entry is not None
    assert entry.wallet_id == owner.id
    assert entry.balance_after_vnd == 65_000


@pytest.mark.asyncio
async def test_zero_balance_becomes_debt(db_session):
    station, _, _, driver, wallet, charging = await create_fixture(
        db_session, initial_balance=0
    )
    assert wallet.balance_vnd == 0
    invoice = make_invoice(charging, station, driver, total_vnd=15_000)
    db_session.add(invoice)
    await db_session.flush()
    entry = await tru_vi(db_session, invoice=invoice)
    assert entry is not None
    assert entry.balance_after_vnd == -15_000
    await db_session.refresh(wallet)
    total, issues = await wallet_issues(db_session, wallet)
    assert total == wallet.balance_vnd == -15_000
    assert issues == []


@pytest.mark.asyncio
async def test_mismatched_session_and_invalid_money_rejected(db_session):
    station, _, _, driver, wallet, charging = await create_fixture(db_session)
    invoice = make_invoice(charging, station, driver, total_vnd=10_000)
    with pytest.raises(ValueError, match="cùng phiên"):
        await tru_vi(db_session, invoice=invoice, session_id=charging.id + 1)
    for amount in (True, Decimal("1.5"), 2**63):
        invalid = make_invoice(charging, station, driver, total_vnd=amount)
        with pytest.raises(WalletAmountError):
            await tru_vi(db_session, invoice=invalid)
    await db_session.refresh(wallet)
    assert wallet.balance_vnd == 100_000


@pytest.mark.asyncio
@pytest.mark.parametrize("same_session", [True, False])
async def test_concurrent_debits_use_separate_connections(
    isolated_wallet_db, same_session
):
    factory = isolated_wallet_db
    async with factory() as session:
        station, charger, connector, driver, wallet, charging = await create_fixture(
            session, initial_balance=50_000
        )
        first = make_invoice(charging, station, driver, total_vnd=35_000)
        session.add(first)
        await session.flush()
        session_ids = [charging.id, charging.id]
        if not same_session:
            second = ChargingSession(
                charge_point_id=charger.id,
                connector_id=connector.id,
                driver_id=driver.id,
                tag_tail="ABCD",
                authorization_status="Accepted",
                started_at=STAMP + timedelta(hours=2),
                ended_at=STAMP + timedelta(hours=3),
                meter_start_wh=Decimal(10_000),
                meter_stop_wh=Decimal(15_000),
                review_reasons=[],
                billing_lifecycle_version=0,
            )
            session.add(second)
            await session.flush()
            session.add(make_invoice(second, station, driver, total_vnd=20_000))
            session_ids[1] = second.id
        wallet_id = wallet.id
        await session.commit()
    ready = asyncio.Barrier(2)

    async def worker(session_id):
        async with factory() as session:
            pid = await session.scalar(text("SELECT pg_backend_pid()"))
            await ready.wait()
            entry = await tru_vi(session, session_id=session_id)
            assert entry is not None
            entry_id = entry.id
            await session.commit()
            return pid, entry_id

    results = await asyncio.wait_for(
        asyncio.gather(*(worker(identifier) for identifier in session_ids)), 30
    )
    assert len({pid for pid, _ in results}) == 2
    assert len({entry_id for _, entry_id in results}) == (1 if same_session else 2)
    async with factory() as session:
        wallet = await session.scalar(
            select(Wallet).where(Wallet.id == wallet_id).with_for_update()
        )
        assert wallet is not None
        assert wallet.balance_vnd == (15_000 if same_session else -5_000)
        assert await session.scalar(
            select(func.count())
            .select_from(WalletLedger)
            .where(
                WalletLedger.wallet_id == wallet_id,
                WalletLedger.entry_type == "charging_debit",
            )
        ) == (1 if same_session else 2)
        total, issues = await wallet_issues(session, wallet)
        assert total == wallet.balance_vnd
        assert issues == []


@pytest.mark.asyncio
async def test_outer_rollback_removes_invoice_debit_and_balance_change(
    isolated_wallet_db,
):
    factory = isolated_wallet_db
    async with factory() as session:
        station, _, _, driver, wallet, charging = await create_fixture(
            session, initial_balance=50_000
        )
        charging_id, wallet_id = charging.id, wallet.id
        station_id, driver_id = station.id, driver.id
        await session.commit()
    async with factory() as writer, factory() as observer:
        invoice = Invoice(
            session_id=charging_id,
            station_id=station_id,
            driver_id=driver_id,
            total_vnd=20_000,
            rounding_rule="half_up",
        )
        writer.add(invoice)
        await writer.flush()
        await tru_vi(writer, invoice=invoice)
        # No internal commit: a different connection still sees the old state.
        assert (await observer.get(Wallet, wallet_id)).balance_vnd == 50_000
        assert (
            await observer.scalar(
                select(Invoice.id).where(Invoice.session_id == charging_id)
            )
            is None
        )
        await writer.rollback()
    async with factory() as observer:
        assert (await observer.get(Wallet, wallet_id)).balance_vnd == 50_000
        assert (
            await observer.scalar(
                select(Invoice.id).where(Invoice.session_id == charging_id)
            )
            is None
        )
        assert (
            await observer.scalar(
                select(WalletLedger.id).where(
                    WalletLedger.entry_type == "charging_debit",
                    WalletLedger.reference_id == str(charging_id),
                )
            )
            is None
        )
