"""T-103 / S-37: Concurrency & Stress Integration Tests.

Verifies the 4 acceptance criteria under Story S-37 / Task T-103:
1. Hai phiên của một tài xế chốt cùng lúc: số dư cuối = số dư đầu - tổng hai hoá đơn.
2. Hai tiến trình cùng chốt một phiên: chỉ tạo 1 hoá đơn, trừ ví đúng 1 lần.
3. Ví thiếu tiền thì âm: cho phép số dư âm (nợ), ghi đầy đủ sổ cái và đánh dấu debited.
4. Lỗi giữa chừng: rollback toàn bộ transaction, không để lại hoá đơn mồ côi.
5. Vòng lặp nghiệm thu 50 lần: chạy lặp lại 50 chu kỳ kiểm thử đồng thời không lần nào sai lệch.
"""

import asyncio
from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from src.modules.billing import closure
from src.modules.billing.closure import chot_phien
from src.modules.billing.models import Invoice
from src.modules.charging.models import ChargingSession
from src.modules.pricing.models import Tariff, TariffBand
from src.modules.wallet.models import Wallet, WalletLedger
from tests.test_charging_sessions import setup
from tests.test_effective_tariffs import committed_tariff_db as isolated_closure_db
from tests.test_t80_invoicing import STAMP, seed

committed_tariff_db = isolated_closure_db


@pytest.fixture
async def factory(committed_tariff_db, monkeypatch):
    """Provide isolated PostgreSQL sessionmaker and bind closure.SessionFactory."""
    monkeypatch.setattr(closure, "SessionFactory", committed_tariff_db)
    return committed_tariff_db


async def create_driver_with_sessions(
    factory,
    *,
    initial_balance: int = 500_000,
    session_kwh_list: list[int],
):
    """Create 1 station, 1 charger, 1 tariff, 1 driver with custom balance, and N sessions."""
    async with factory() as db, db.begin():
        station, charger, connector, driver, *_ = await setup(db)

        # Set specific initial balance and initial ledger
        wallet = await db.scalar(select(Wallet).where(Wallet.driver_id == driver.id))
        assert wallet is not None
        wallet.balance_vnd = initial_balance
        if initial_balance > 0:
            db.add(
                WalletLedger(
                    wallet_id=wallet.id,
                    entry_type="manual_topup",
                    amount_vnd=initial_balance,
                    balance_after_vnd=initial_balance,
                    reference_type="initial_setup",
                    reference_id=f"init_{uuid4()}",
                )
            )

        # Ensure active tariff: 3,000 VND / kWh
        tariff = Tariff(
            station_id=station.id,
            effective_from=STAMP.date(),
            idle_rate_vnd_per_minute=200,
            grace_minutes=5,
        )
        db.add(tariff)
        await db.flush()

        db.add(
            TariffBand(
                tariff_id=tariff.id,
                start_min=0,
                end_min=1440,
                energy_rate_vnd_per_kwh=3000,
                label="Tiêu chuẩn",
            )
        )
        await db.flush()

        session_ids = []
        for i, kwh in enumerate(session_kwh_list):
            cs = ChargingSession(
                charge_point_id=charger.id,
                connector_id=connector.id,
                driver_id=driver.id,
                tag_tail=f"T{i}",
                authorization_status="Accepted",
                started_at=STAMP + timedelta(hours=i * 2),
                ended_at=STAMP + timedelta(hours=i * 2 + 1),
                meter_start_wh=Decimal(0),
                meter_stop_wh=Decimal(kwh * 1000),
                review_reasons=[],
                billing_lifecycle_version=0,
            )
            db.add(cs)
            await db.flush()
            session_ids.append(cs.id)

        return driver.id, wallet.id, session_ids


# ---------------------------------------------------------------------------
# Kịch bản 1: Hai phiên của một tài xế chốt cùng lúc
# ---------------------------------------------------------------------------
async def test_t103_hai_phien_cung_tai_xe_chot_dong_thoi(factory):
    """Hai phiên của một tài xế chốt cùng lúc:

    - Số dư cuối bằng số dư đầu trừ tổng hai hoá đơn.
    - Sổ cái ghi nhận đủ 2 dòng charging_debit.
    - Tổng sổ cái khớp 100% với số dư hiện tại của ví.
    """
    initial_balance = 200_000
    # Phiên 1: 5 kWh (15.000đ), Phiên 2: 10 kWh (30.000đ)
    _driver_id, wallet_id, (s1, s2) = await create_driver_with_sessions(
        factory,
        initial_balance=initial_balance,
        session_kwh_list=[5, 10],
    )

    # Chốt 2 phiên đồng thời qua 2 kết nối độc lập
    res1, res2 = await asyncio.gather(
        chot_phien(s1, settle=True),
        chot_phien(s2, settle=True),
    )

    assert res1.status == "ready" and res1.invoice is not None
    assert res2.status == "ready" and res2.invoice is not None

    inv1_total = res1.invoice.total_vnd
    inv2_total = res2.invoice.total_vnd
    expected_final_balance = initial_balance - (inv1_total + inv2_total)

    async with factory() as db:
        wallet = await db.get(Wallet, wallet_id)
        assert wallet is not None
        assert wallet.balance_vnd == expected_final_balance

        # Kiểm tra 2 dòng debit trong wallet_ledger
        ledgers = list(
            await db.scalars(
                select(WalletLedger)
                .where(
                    WalletLedger.wallet_id == wallet_id,
                    WalletLedger.entry_type == "charging_debit",
                )
                .order_by(WalletLedger.id)
            )
        )
        assert len(ledgers) == 2
        debit_amounts = {l.amount_vnd for l in ledgers}
        assert debit_amounts == {-inv1_total, -inv2_total}

        ref_ids = {l.reference_id for l in ledgers}
        assert ref_ids == {str(s1), str(s2)}

        # Đối chiếu tổng sổ cái khớp số dư ví
        total_ledger = await db.scalar(
            select(func.coalesce(func.sum(WalletLedger.amount_vnd), 0)).where(
                WalletLedger.wallet_id == wallet_id
            )
        )
        assert total_ledger == wallet.balance_vnd

        # Cả 2 phiên đều có trạng thái debited và thời gian chốt
        c1 = await db.get(ChargingSession, s1)
        c2 = await db.get(ChargingSession, s2)
        assert (
            c1.settlement_reason == "debited" and c1.settlement_completed_at is not None
        )
        assert (
            c2.settlement_reason == "debited" and c2.settlement_completed_at is not None
        )


# ---------------------------------------------------------------------------
# Kịch bản 2: Hai tiến trình cùng chốt MỘT PHIÊN SẠC
# ---------------------------------------------------------------------------
async def test_t103_hai_tien_trinh_cung_chot_mot_phien_race_condition(factory):
    """Hai (hoặc 4) tiến trình cùng gọi chot_phien trên cùng một phiên:

    - Nhờ khoá dòng with_for_update và kiểm tra settlement:
    - Chỉ tạo ĐÚNG 1 hoá đơn.
    - Chỉ trừ tiền ví ĐÚNG 1 lần (1 dòng ledger).
    - Mọi tiến trình đều nhận được kết quả ready hợp lệ cùng invoice ID.
    """
    async with factory() as db, db.begin():
        charging, *_ = await seed(db, last=5000)
        session_id = charging.id

    # 4 worker cùng gọi chot_phien song song
    outcomes = await asyncio.gather(
        *(chot_phien(session_id, settle=True) for _ in range(4))
    )

    assert all(o.status == "ready" for o in outcomes)
    invoice_ids = {o.invoice.id for o in outcomes if o.invoice is not None}
    assert len(invoice_ids) == 1

    async with factory() as db:
        invoice_count = await db.scalar(
            select(func.count())
            .select_from(Invoice)
            .where(Invoice.session_id == session_id)
        )
        assert invoice_count == 1

        ledger_count = await db.scalar(
            select(func.count())
            .select_from(WalletLedger)
            .where(
                WalletLedger.reference_type == "charging_session",
                WalletLedger.reference_id == str(session_id),
            )
        )
        assert ledger_count == 1

        charging = await db.get(ChargingSession, session_id)
        assert charging.settlement_reason == "debited"
        assert charging.settlement_completed_at is not None


# ---------------------------------------------------------------------------
# Kịch bản 3: Ví thiếu tiền thì số dư âm (debt balance)
# ---------------------------------------------------------------------------
async def test_t103_vi_thieu_tien_van_tru_de_so_du_am(factory):
    """Ví có số dư nhỏ hơn hoá đơn vẫn trừ bình thường, số dư chuyển sang âm.

    Thử nghiệm đồng thời 2 phiên vượt số dư:
    - Ví ban đầu: 10.000đ.
    - Hai phiên sạc đồng thời mỗi phiên 15.000đ (tổng 30.000đ).
    - Cả 2 đều chốt thành công, số dư cuối = -20.000đ.
    """
    initial_balance = 10_000
    _driver_id, wallet_id, (s1, s2) = await create_driver_with_sessions(
        factory,
        initial_balance=initial_balance,
        session_kwh_list=[5, 5],  # 5 kWh = 15.000đ mỗi phiên
    )

    res1, res2 = await asyncio.gather(
        chot_phien(s1, settle=True),
        chot_phien(s2, settle=True),
    )

    assert res1.status == "ready" and res2.status == "ready"
    inv1_total = res1.invoice.total_vnd
    inv2_total = res2.invoice.total_vnd
    assert inv1_total + inv2_total > initial_balance

    async with factory() as db:
        wallet = await db.get(Wallet, wallet_id)
        assert wallet is not None
        assert wallet.balance_vnd == initial_balance - (inv1_total + inv2_total)
        assert wallet.balance_vnd < 0  # Số dư âm thể hiện nợ

        # 2 bản ghi debit đều được tạo đầy đủ
        ledgers = list(
            await db.scalars(
                select(WalletLedger).where(
                    WalletLedger.wallet_id == wallet_id,
                    WalletLedger.entry_type == "charging_debit",
                )
            )
        )
        assert len(ledgers) == 2

        # Cả 2 phiên đều đánh dấu debited thành công
        c1 = await db.get(ChargingSession, s1)
        c2 = await db.get(ChargingSession, s2)
        assert (
            c1.settlement_reason == "debited" and c1.settlement_completed_at is not None
        )
        assert (
            c2.settlement_reason == "debited" and c2.settlement_completed_at is not None
        )


# ---------------------------------------------------------------------------
# Kịch bản 4: Lỗi giữa chừng rollback toàn bộ, không mồ côi hoá đơn
# ---------------------------------------------------------------------------
async def test_t103_loi_giua_chung_khong_de_lai_hoa_don_mo_coi(factory, monkeypatch):
    """Khi có lỗi bất ngờ ở bước trừ ví / commit:

    - Toàn bộ transaction rollback sạch sẽ.
    - Không để lại hoá đơn mồ côi trong bảng invoices.
    - Không có dòng trừ tiền mồ côi trong wallet_ledger.
    - Sau khi sửa lỗi/thử lại, phiên được chốt và trừ ví thành công trọn vẹn.
    """
    async with factory() as db, db.begin():
        charging, *_ = await seed(db, last=5000)
        session_id = charging.id

    original_tru_vi = closure.tru_vi

    # Giả lập lỗi ở bước trừ ví
    async def fail_tru_vi(*args, **kwargs):
        raise SQLAlchemyError("Giả lập lỗi database bất ngờ trong giao dịch")

    monkeypatch.setattr(closure, "tru_vi", fail_tru_vi)

    async with factory() as db:
        with pytest.raises(SQLAlchemyError):
            async with db.begin():
                await chot_phien(session_id, db=db, settle=True)

    # Khẳng định không có hoá đơn hoặc dòng ví nào mồ côi
    async with factory() as db:
        inv = await db.scalar(select(Invoice).where(Invoice.session_id == session_id))
        assert inv is None

        ledger = await db.scalar(
            select(WalletLedger).where(WalletLedger.reference_id == str(session_id))
        )
        assert ledger is None

        cs = await db.get(ChargingSession, session_id)
        assert cs.settlement_completed_at is None
        assert cs.settlement_reason is None

    # Khôi phục bình thường: chốt lại thành công
    monkeypatch.setattr(closure, "tru_vi", original_tru_vi)
    retry_outcome = await chot_phien(session_id, settle=True)
    assert retry_outcome.status == "ready"

    async with factory() as db:
        cs = await db.get(ChargingSession, session_id)
        assert cs.settlement_reason == "debited"
        assert cs.settlement_completed_at is not None


# ---------------------------------------------------------------------------
# Kịch bản 5: Nghiệm thu lặp 50 lần liên tục (50-iteration Stress Run)
# ---------------------------------------------------------------------------
async def test_t103_nghiem_thu_50_lan_dong_thoi_khong_sai_lech(factory):
    """Yêu cầu đặc tả: 'Bốn test xanh, lặp 50 lần không lần nào lệch'.

    Mỗi vòng lặp:
    1. Chốt đồng thời 2 phiên của cùng 1 tài xế.
    2. Chốt đồng thời 2 tiến trình trên cùng 1 phiên (double-closure).
    Kiểm tra chặt chẽ:
    - 50/50 vòng lặp đều hoàn thành xuất sắc.
    - Số dư ví luôn bằng chính xác số dư đầu trừ tổng các hoá đơn.
    - Tổng bảng sổ cái khớp hoàn hảo với balance của ví.
    """
    # Khởi tạo 1 môi trường tài xế dùng cho 50 vòng lặp để tối ưu tốc độ chạy
    async with factory() as db, db.begin():
        station, charger, connector, driver, *_ = await setup(db)
        wallet = await db.scalar(select(Wallet).where(Wallet.driver_id == driver.id))
        assert wallet is not None
        wallet.balance_vnd = 10_000_000  # 10 triệu đồng
        db.add(
            WalletLedger(
                wallet_id=wallet.id,
                entry_type="manual_topup",
                amount_vnd=10_000_000,
                balance_after_vnd=10_000_000,
                reference_type="initial_setup",
                reference_id=f"init_{uuid4()}",
            )
        )

        tariff = Tariff(
            station_id=station.id,
            effective_from=STAMP.date(),
            idle_rate_vnd_per_minute=200,
            grace_minutes=5,
        )
        db.add(tariff)
        await db.flush()

        db.add(
            TariffBand(
                tariff_id=tariff.id,
                start_min=0,
                end_min=1440,
                energy_rate_vnd_per_kwh=3000,
                label="Cả ngày",
            )
        )
        await db.flush()
        driver_id = driver.id
        wallet_id = wallet.id
        charger_id = charger.id
        connector_id = connector.id

    current_expected_balance = 10_000_000

    for iteration in range(50):
        # Tạo 2 phiên sạc mới cho iteration này
        async with factory() as db, db.begin():
            s1 = ChargingSession(
                charge_point_id=charger_id,
                connector_id=connector_id,
                driver_id=driver_id,
                tag_tail=f"L{iteration}A",
                authorization_status="Accepted",
                started_at=STAMP + timedelta(minutes=iteration * 10),
                ended_at=STAMP + timedelta(minutes=iteration * 10 + 30),
                meter_start_wh=Decimal(0),
                meter_stop_wh=Decimal(1000),  # 1 kWh = 3000đ
                review_reasons=[],
                billing_lifecycle_version=0,
            )
            s2 = ChargingSession(
                charge_point_id=charger_id,
                connector_id=connector_id,
                driver_id=driver_id,
                tag_tail=f"L{iteration}B",
                authorization_status="Accepted",
                started_at=STAMP + timedelta(minutes=iteration * 10 + 1),
                ended_at=STAMP + timedelta(minutes=iteration * 10 + 31),
                meter_start_wh=Decimal(0),
                meter_stop_wh=Decimal(2000),  # 2 kWh = 6000đ
                review_reasons=[],
                billing_lifecycle_version=0,
            )
            db.add_all([s1, s2])
            await db.flush()
            s1_id, s2_id = s1.id, s2.id

        # Kiểm tra 1: Đồng thời chốt s1 qua 2 connection (race double closure)
        # Kiểm tra 2: Đồng thời chốt s2 song song với s1 (concurrent sessions for driver)
        res_s1_a, res_s1_b, res_s2 = await asyncio.gather(
            chot_phien(s1_id, settle=True),
            chot_phien(s1_id, settle=True),
            chot_phien(s2_id, settle=True),
        )

        assert res_s1_a.status == "ready" and res_s1_b.status == "ready"
        assert res_s2.status == "ready"
        assert res_s1_a.invoice.id == res_s1_b.invoice.id

        deducted = res_s1_a.invoice.total_vnd + res_s2.invoice.total_vnd
        current_expected_balance -= deducted

        # Kiểm tra khớp số dư ví sau mỗi vòng lặp
        async with factory() as db:
            w = await db.get(Wallet, wallet_id)
            assert w.balance_vnd == current_expected_balance, (
                f"Lệch số dư tại vòng lặp {iteration}: thực tế {w.balance_vnd} != kỳ vọng {current_expected_balance}"
            )

    # Sau cả 50 vòng lặp, kiểm tra tổng sổ cái đối soát
    async with factory() as db:
        total_ledger = await db.scalar(
            select(func.coalesce(func.sum(WalletLedger.amount_vnd), 0)).where(
                WalletLedger.wallet_id == wallet_id
            )
        )
        w = await db.get(Wallet, wallet_id)
        assert total_ledger == w.balance_vnd
        assert w.balance_vnd == current_expected_balance
