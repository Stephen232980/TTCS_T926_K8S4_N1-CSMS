from datetime import date, datetime, timedelta
from decimal import Decimal
from time import perf_counter
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import insert, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.billing.models import Invoice, InvoiceLine
from src.modules.charging.models import ChargingCard, ChargingSession
from src.modules.identity.models import User
from src.modules.pricing.models import Tariff
from src.modules.reporting.schemas import RevenueReportQuery
from src.modules.reporting.service import REPORT_TIMEZONE, get_revenue_report
from src.modules.reservations.models import Reservation
from src.modules.stations.models import ChargePoint, Connector, Station
from src.modules.wallet.models import Wallet, WalletLedger


async def _create_test_environment(session: AsyncSession):
    """Sets up owner, driver, wallet, card, station, charge point, connector, tariff."""
    owner = User(email=f"owner-{uuid4()}@example.com", password_hash="test")
    driver = User(email=f"driver-{uuid4()}@example.com", password_hash="test")
    session.add_all([owner, driver])
    await session.flush()

    wallet = Wallet(driver_id=driver.id, balance_vnd=1000000, status="active")
    session.add(wallet)
    await session.flush()

    card = ChargingCard(
        tag_hash=f"hash-{uuid4()}"[:64],
        tag_tail="9999",
        driver_id=driver.id,
        issuer_id=owner.id,
        status="active",
    )
    session.add(card)
    await session.flush()

    station = Station(
        owner_id=owner.id,
        name=f"Station-{uuid4()}"[:30],
        address="123 Vo Van Kiet, TP.HCM",
        latitude=Decimal("10.7769"),
        longitude=Decimal("106.7009"),
        status="active",
        timezone="Asia/Ho_Chi_Minh",
    )
    session.add(station)
    await session.flush()

    cp = ChargePoint(station_id=station.id, code=f"CP-{uuid4()}"[:20])
    session.add(cp)
    await session.flush()

    connector = Connector(
        charge_point_id=cp.id,
        connector_number=1,
        status="Available",
    )
    session.add(connector)

    tariff = Tariff(
        station_id=station.id,
        effective_from=date(2026, 1, 1),
        idle_rate_vnd_per_minute=1000,
        grace_minutes=15,
    )
    session.add(tariff)
    await session.flush()

    return owner, driver, wallet, card, station, cp, connector, tariff


@pytest.mark.asyncio
async def test_cross_month_cohort_invoice_oct_debit_nov(db_session: AsyncSession):
    """AC-3 / P1: Hóa đơn 38.500đ ngày 31/10, debit ngày 01/11:

    - Tháng 10: Doanh thu hóa đơn = 38.500đ, debited_vnd = 0đ.
    - Tháng 11: Doanh thu hóa đơn = 0đ, debited_vnd = 38.500đ.
    """
    (
        owner,
        driver,
        wallet,
        _card,
        station,
        cp,
        connector,
        tariff,
    ) = await _create_test_environment(db_session)

    # Oct 31 23:30 VN = Oct 31 16:30 UTC
    oct_end = datetime(2026, 10, 31, 23, 30, tzinfo=REPORT_TIMEZONE)
    # Nov 01 00:05 VN = Oct 31 17:05 UTC
    nov_start = datetime(2026, 11, 1, 0, 5, tzinfo=REPORT_TIMEZONE)

    session = ChargingSession(
        charge_point_id=cp.id,
        connector_id=connector.id,
        driver_id=driver.id,
        tag_tail="9999",
        authorization_status="Accepted",
        started_at=oct_end - timedelta(minutes=30),
        ended_at=oct_end - timedelta(minutes=5),
        energy_kwh=Decimal("10.0"),
        meter_start_wh=Decimal(0),
        meter_stop_wh=Decimal(10000),
        settlement_reason="debited",
        settlement_completed_at=nov_start,
    )
    db_session.add(session)
    await db_session.flush()

    # Invoice created Oct 31
    invoice = Invoice(
        session_id=session.id,
        driver_id=driver.id,
        station_id=station.id,
        total_vnd=38500,
        rounding_rule="round_half_up",
        created_at=oct_end,
    )
    db_session.add(invoice)
    await db_session.flush()

    line = InvoiceLine(
        invoice_id=invoice.id,
        line_type="energy",
        local_date=oct_end.date(),
        started_at=oct_end - timedelta(minutes=30),
        ended_at=oct_end - timedelta(minutes=5),
        energy_wh=Decimal(10000),
        rate_vnd=3850,
        band_label="Standard",
        interpolated=False,
        tariff_id=tariff.id,
        amount_vnd=38500,
    )
    db_session.add(line)
    await db_session.flush()

    # Debit occurred Nov 01
    debit_entry = WalletLedger(
        wallet_id=wallet.id,
        entry_type="charging_debit",
        amount_vnd=-38500,
        balance_after_vnd=1000000 - 38500,
        reference_type="charging_session",
        reference_id=str(session.id),
        created_at=nov_start,
    )
    db_session.add(debit_entry)
    await db_session.flush()

    # 1. Query October 2026
    oct_query = RevenueReportQuery(
        period="month",
        date_from=date(2026, 10, 1),
        station_id=station.id,
    )
    oct_report = await get_revenue_report(db_session, oct_query, owner_id=owner.id)

    assert oct_report.summary.invoiced_sessions == 1
    assert oct_report.summary.total_invoice_vnd == 38500
    assert oct_report.summary.total_kwh == Decimal("10.0")
    # P1 Requirement: Debited in October is 0 because the debit occurred in November!
    assert oct_report.summary.debited_vnd == 0
    # Cohort was settled:
    assert oct_report.summary.invoice_cohort_settled_vnd == 38500
    assert oct_report.summary.awaiting_settlement_vnd == 0

    # 2. Query November 2026
    nov_query = RevenueReportQuery(
        period="month",
        date_from=date(2026, 11, 1),
        station_id=station.id,
    )
    nov_report = await get_revenue_report(db_session, nov_query, owner_id=owner.id)

    # In November: no invoice was created
    assert nov_report.summary.invoiced_sessions == 0
    assert nov_report.summary.total_invoice_vnd == 0
    assert nov_report.summary.total_kwh == Decimal(0)
    # P1 Requirement: Debit belongs to November!
    assert nov_report.summary.debited_vnd == 38500
    assert nov_report.summary.invoice_cohort_settled_vnd == 0

    # Timeline in November: on 2026-11-01, debited_vnd == 38500
    d_nov1 = next(d for d in nov_report.daily_timeline if d.date == "2026-11-01")
    assert d_nov1.debited_vnd == 38500
    assert d_nov1.invoice_vnd == 0


@pytest.mark.asyncio
async def test_multiline_invoice_does_not_duplicate_sessions(db_session: AsyncSession):
    """AC-6: Hóa đơn có nhiều energy lines và idle lines không nhân số phiên hoặc tiền."""
    (
        owner,
        driver,
        wallet,
        _card,
        station,
        cp,
        connector,
        tariff,
    ) = await _create_test_environment(db_session)

    t = datetime(2026, 11, 15, 10, 0, tzinfo=REPORT_TIMEZONE)
    session = ChargingSession(
        charge_point_id=cp.id,
        connector_id=connector.id,
        driver_id=driver.id,
        tag_tail="9999",
        authorization_status="Accepted",
        started_at=t - timedelta(hours=2),
        ended_at=t - timedelta(minutes=10),
        energy_kwh=Decimal("30.0"),
        meter_start_wh=Decimal(0),
        meter_stop_wh=Decimal(30000),
        settlement_reason="debited",
        settlement_completed_at=t,
    )
    db_session.add(session)
    await db_session.flush()

    invoice = Invoice(
        session_id=session.id,
        driver_id=driver.id,
        station_id=station.id,
        total_vnd=110000,
        rounding_rule="round_half_up",
        created_at=t,
    )
    db_session.add(invoice)
    await db_session.flush()

    # 3 energy lines
    for i, wh, amt in [(1, 10000, 30000), (2, 15000, 45000), (3, 5000, 15000)]:
        db_session.add(
            InvoiceLine(
                invoice_id=invoice.id,
                line_type="energy",
                local_date=t.date(),
                started_at=t - timedelta(hours=2),
                ended_at=t - timedelta(hours=1),
                energy_wh=Decimal(wh),
                rate_vnd=3000,
                band_label=f"Band {i}",
                interpolated=False,
                tariff_id=tariff.id,
                amount_vnd=amt,
            )
        )

    # 2 idle lines
    for i, amt in [(1, 10000), (2, 10000)]:
        db_session.add(
            InvoiceLine(
                invoice_id=invoice.id,
                line_type="idle",
                local_date=t.date(),
                started_at=t - timedelta(minutes=20),
                ended_at=t - timedelta(minutes=10),
                energy_wh=Decimal(0),
                rate_vnd=1000,
                band_label=f"Idle {i}",
                interpolated=False,
                tariff_id=tariff.id,
                amount_vnd=amt,
            )
        )
    await db_session.flush()

    # Debit
    db_session.add(
        WalletLedger(
            wallet_id=wallet.id,
            entry_type="charging_debit",
            amount_vnd=-110000,
            balance_after_vnd=890000,
            reference_type="charging_session",
            reference_id=str(session.id),
            created_at=t,
        )
    )
    await db_session.flush()

    query = RevenueReportQuery(
        period="month",
        date_from=date(2026, 11, 1),
        station_id=station.id,
    )
    report = await get_revenue_report(db_session, query, owner_id=owner.id)

    # Must be exactly 1 invoiced session and exact sums
    assert report.summary.invoiced_sessions == 1
    assert report.summary.total_invoice_vnd == 110000
    assert report.summary.energy_amount_vnd == 90000
    assert report.summary.idle_amount_vnd == 20000
    assert report.summary.total_kwh == Decimal("30.0")
    assert report.summary.debited_vnd == 110000
    assert report.summary.awaiting_settlement_vnd == 0


@pytest.mark.asyncio
async def test_revenue_classifications_topup_noshow_free_legacy(
    db_session: AsyncSession,
):
    """AC-4/5/7: Phân loại khoản thu:

    - Topup ví loại khỏi doanh thu sạc.
    - No-show reservation fee hiển thị riêng, không cộng vào kWh.
    - Legacy exempt hiển thị riêng, không cộng vào awaiting_settlement_vnd.
    - Free session hiển thị riêng.
    - Debit sai wallet/reference bị từ chối.
    - Phiên unbilled thiếu meter không ép về 0.
    """
    (
        owner,
        driver,
        wallet,
        card,
        station,
        cp,
        connector,
        tariff,
    ) = await _create_test_environment(db_session)
    t = datetime(2026, 11, 10, 12, 0, tzinfo=REPORT_TIMEZONE)

    # 1. Topup transactions: gateway & manual
    topup_gateway = WalletLedger(
        wallet_id=wallet.id,
        entry_type="gateway_topup",
        amount_vnd=500000,
        balance_after_vnd=1500000,
        reference_type="vnpay",
        reference_id=f"vnpay-{uuid4()}",
        created_at=t,
    )
    topup_manual = WalletLedger(
        wallet_id=wallet.id,
        entry_type="manual_topup",
        amount_vnd=100000,
        balance_after_vnd=1600000,
        reference_type="cash_admin",
        reference_id=f"cash-{uuid4()}",
        created_at=t,
    )
    db_session.add_all([topup_gateway, topup_manual])

    # 2. Legacy exempt invoice: 38,500 VND
    s_legacy = ChargingSession(
        charge_point_id=cp.id,
        connector_id=connector.id,
        driver_id=driver.id,
        tag_tail="9999",
        authorization_status="Accepted",
        started_at=t - timedelta(hours=3),
        ended_at=t - timedelta(hours=2),
        energy_kwh=Decimal("10.0"),
        meter_start_wh=Decimal(0),
        meter_stop_wh=Decimal(10000),
        settlement_reason="legacy_exempt",
        settlement_completed_at=t - timedelta(hours=2),
    )
    db_session.add(s_legacy)
    await db_session.flush()

    inv_legacy = Invoice(
        session_id=s_legacy.id,
        driver_id=driver.id,
        station_id=station.id,
        total_vnd=38500,
        rounding_rule="round_half_up",
        created_at=t,
    )
    db_session.add(inv_legacy)
    await db_session.flush()

    db_session.add(
        InvoiceLine(
            invoice_id=inv_legacy.id,
            line_type="energy",
            local_date=t.date(),
            started_at=t - timedelta(hours=3),
            ended_at=t - timedelta(hours=2),
            energy_wh=Decimal(10000),
            rate_vnd=3850,
            band_label="Legacy",
            interpolated=False,
            tariff_id=tariff.id,
            amount_vnd=38500,
        )
    )

    # 3. Free session (zero_invoice): 0 VND
    s_free = ChargingSession(
        charge_point_id=cp.id,
        connector_id=connector.id,
        driver_id=driver.id,
        tag_tail="9999",
        authorization_status="Accepted",
        started_at=t - timedelta(hours=2),
        ended_at=t - timedelta(hours=1),
        energy_kwh=Decimal("5.0"),
        meter_start_wh=Decimal(0),
        meter_stop_wh=Decimal(5000),
        settlement_reason="zero_invoice",
        settlement_completed_at=t - timedelta(hours=1),
    )
    db_session.add(s_free)
    await db_session.flush()

    inv_free = Invoice(
        session_id=s_free.id,
        driver_id=driver.id,
        station_id=station.id,
        total_vnd=0,
        rounding_rule="round_half_up",
        created_at=t,
    )
    db_session.add(inv_free)
    await db_session.flush()

    db_session.add(
        InvoiceLine(
            invoice_id=inv_free.id,
            line_type="energy",
            local_date=t.date(),
            started_at=t - timedelta(hours=2),
            ended_at=t - timedelta(hours=1),
            energy_wh=Decimal(5000),
            rate_vnd=0,
            band_label="Promo",
            interpolated=False,
            tariff_id=tariff.id,
            amount_vnd=0,
        )
    )

    # 4. No-show reservation fee: 50,000 VND
    reservation = Reservation(
        id=uuid4(),
        driver_id=driver.id,
        station_id=station.id,
        charge_point_id=cp.id,
        connector_id=connector.id,
        card_id=card.id,
        request_hash=f"req-{uuid4()}"[:64],
        status="expired",
        created_at=t - timedelta(hours=2),
        arrival_at=t - timedelta(hours=1),
        expires_at=t - timedelta(minutes=30),
        updated_at=t,
        fee_vnd=50000,
        fee_decision="charged",
    )
    db_session.add(reservation)
    await db_session.flush()

    res_ledger = WalletLedger(
        wallet_id=wallet.id,
        entry_type="reservation_fee",
        amount_vnd=-50000,
        balance_after_vnd=1550000,
        reference_type="reservation",
        reference_id=str(reservation.id),
        created_at=t,
    )
    db_session.add(res_ledger)

    # 5. Invalid / spoofed debit: debit with driver mismatch must be ignored
    other_user = User(email=f"other-{uuid4()}@example.com", password_hash="test")
    db_session.add(other_user)
    await db_session.flush()
    other_wallet = Wallet(driver_id=other_user.id, balance_vnd=500000, status="active")
    db_session.add(other_wallet)
    await db_session.flush()

    spoofed_debit = WalletLedger(
        wallet_id=other_wallet.id,  # not driver.id!
        entry_type="charging_debit",
        amount_vnd=-20000,
        balance_after_vnd=480000,
        reference_type="charging_session",
        reference_id=str(s_legacy.id),
        created_at=t,
    )
    db_session.add(spoofed_debit)

    # 6. Unbilled session missing meter: energy_kwh=None
    s_missing_meter = ChargingSession(
        charge_point_id=cp.id,
        connector_id=connector.id,
        driver_id=driver.id,
        tag_tail="9999",
        authorization_status="Accepted",
        started_at=t - timedelta(minutes=40),
        ended_at=t - timedelta(minutes=10),
        energy_kwh=None,  # Missing meter!
        meter_start_wh=Decimal(0),
        meter_stop_wh=None,
    )
    db_session.add(s_missing_meter)
    await db_session.flush()

    # Query report
    query = RevenueReportQuery(
        period="month",
        date_from=date(2026, 11, 1),
        station_id=station.id,
    )
    report = await get_revenue_report(db_session, query, owner_id=owner.id)

    # Verify AC-7: Legacy exempt is isolated and NOT in awaiting_settlement_vnd
    assert report.summary.legacy_exempt_sessions == 1
    assert report.summary.legacy_exempt_vnd == 38500
    assert report.summary.awaiting_settlement_vnd == 0
    assert report.summary.awaiting_settlement_sessions == 0

    # Verify AC-7: Free session is isolated
    assert report.summary.free_sessions == 1

    # Verify AC-4: Reservation fee isolated from kWh
    assert report.summary.reservation_fee_vnd == 50000
    assert report.summary.reservation_count == 1
    # Total kWh only includes the invoiced sessions: 10 kWh (legacy) + 5 kWh (free) = 15 kWh
    assert report.summary.total_kwh == Decimal("15.0")

    # Verify topup and spoofed debit are completely ignored:
    # Topups are not debits; spoofed debit has driver mismatch
    assert report.summary.debited_vnd == 0

    # Verify AC-5: Missing meter is marked, not treated as confirmed 0 kWh
    assert report.summary.unbilled_sessions == 1
    assert report.summary.unbilled_missing_meter_sessions == 1
    assert report.summary.unbilled_operating_kwh == Decimal(0)


@pytest.mark.asyncio
async def test_pagination_and_owner_isolation(db_session: AsyncSession):
    """NFR-2 & Security: Phân trang khớp tổng toàn tập và cách ly dữ liệu giữa các chủ trạm."""
    (
        owner_a,
        driver_a,
        wallet_a,
        _card_a,
        station_a,
        cp_a,
        conn_a,
        tariff_a,
    ) = await _create_test_environment(db_session)
    (
        owner_b,
        _driver_b,
        _wallet_b,
        _card_b,
        _station_b,
        _cp_b,
        _conn_b,
        _tariff_b,
    ) = await _create_test_environment(db_session)

    t = datetime(2026, 11, 5, 12, 0, tzinfo=REPORT_TIMEZONE)

    # Create 3 charge points for owner_a
    cps_a = [cp_a]
    for i in range(2):
        new_cp = ChargePoint(station_id=station_a.id, code=f"CP-A-{i}-{uuid4()}"[:20])
        db_session.add(new_cp)
        await db_session.flush()
        new_conn = Connector(
            charge_point_id=new_cp.id, connector_number=1, status="Available"
        )
        db_session.add(new_conn)
        cps_a.append(new_cp)
    await db_session.flush()

    # Create invoices for all 3 CPs of owner_a
    total_expected_vnd = 0
    for idx, cp_item in enumerate(cps_a):
        inv_amt = (idx + 1) * 20000
        total_expected_vnd += inv_amt
        s = ChargingSession(
            charge_point_id=cp_item.id,
            connector_id=conn_a.id,
            driver_id=driver_a.id,
            tag_tail="9999",
            authorization_status="Accepted",
            started_at=t - timedelta(hours=1),
            ended_at=t,
            energy_kwh=Decimal("5.0"),
            meter_start_wh=Decimal(0),
            settlement_reason="debited",
            settlement_completed_at=t,
        )
        db_session.add(s)
        await db_session.flush()

        inv = Invoice(
            session_id=s.id,
            driver_id=driver_a.id,
            station_id=station_a.id,
            total_vnd=inv_amt,
            rounding_rule="round_half_up",
            created_at=t,
        )
        db_session.add(inv)
        await db_session.flush()

        db_session.add(
            InvoiceLine(
                invoice_id=inv.id,
                line_type="energy",
                local_date=t.date(),
                started_at=t - timedelta(hours=1),
                ended_at=t,
                energy_wh=Decimal(5000),
                rate_vnd=inv_amt // 5,
                band_label="Tier",
                interpolated=False,
                tariff_id=tariff_a.id,
                amount_vnd=inv_amt,
            )
        )
        db_session.add(
            WalletLedger(
                wallet_id=wallet_a.id,
                entry_type="charging_debit",
                amount_vnd=-inv_amt,
                balance_after_vnd=1000000 - inv_amt,
                reference_type="charging_session",
                reference_id=str(s.id),
                created_at=t,
            )
        )
    await db_session.flush()

    # 1. Test pagination on Owner A (page_size = 2, total 3 items)
    q_page1 = RevenueReportQuery(
        period="month",
        date_from=date(2026, 11, 1),
        station_id=station_a.id,
        page=1,
        page_size=2,
    )
    res_p1 = await get_revenue_report(db_session, q_page1, owner_id=owner_a.id)

    q_page2 = RevenueReportQuery(
        period="month",
        date_from=date(2026, 11, 1),
        station_id=station_a.id,
        page=2,
        page_size=2,
    )
    res_p2 = await get_revenue_report(db_session, q_page2, owner_id=owner_a.id)

    # Full collection total must match across pages
    assert res_p1.summary.total_invoice_vnd == total_expected_vnd
    assert res_p2.summary.total_invoice_vnd == total_expected_vnd
    assert res_p1.summary.invoiced_sessions == 3
    assert res_p2.summary.invoiced_sessions == 3
    assert res_p1.pagination.total_items == 3
    assert res_p1.pagination.total_pages == 2
    assert len(res_p1.charge_points) == 2
    assert len(res_p2.charge_points) == 1

    # 2. Test Cross-Owner Isolation: Owner B cannot read Owner A's station
    q_unauth = RevenueReportQuery(
        period="month",
        date_from=date(2026, 11, 1),
        station_id=station_a.id,
    )
    with pytest.raises(HTTPException) as exc_info:
        await get_revenue_report(db_session, q_unauth, owner_id=owner_b.id)
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_benchmark_10k_sessions_50_chargers_p95_under_2s(
    db_session: AsyncSession,
):
    """Ca nghiệm thu: Benchmark p95 <= 2s với 10.000 phiên / 50 trụ.

    Môi trường: Windows PostgreSQL 16 (local async psycopg)
    Phương pháp: Bulk-insert 10.000 phiên sạc qua 50 trụ, chạy truy vấn 5 lần, tính p95.
    """
    (
        owner,
        driver,
        wallet,
        _card,
        station,
        cp_base,
        connector_base,
        tariff,
    ) = await _create_test_environment(db_session)

    t_start = datetime(2026, 11, 1, 0, 0, tzinfo=REPORT_TIMEZONE)
    # Bulk create 50 charge points
    cp_ids = [cp_base.id]
    conn_ids = [connector_base.id]

    new_cps = []
    for i in range(49):
        new_cps.append(
            {
                "id": uuid4(),
                "station_id": station.id,
                "code": f"BENCH-CP-{i:02d}-{uuid4()}"[:20],
            }
        )
    if new_cps:
        await db_session.execute(insert(ChargePoint).values(new_cps))
        await db_session.flush()
        for cp_dict in new_cps:
            cp_ids.append(cp_dict["id"])

    # Create connectors for new CPs
    new_conns = []
    for cpid in cp_ids[1:]:
        new_conns.append(
            {
                "id": uuid4(),
                "charge_point_id": cpid,
                "connector_number": 1,
                "status": "Available",
            }
        )
    if new_conns:
        await db_session.execute(insert(Connector).values(new_conns))
        await db_session.flush()
        for conn_dict in new_conns:
            conn_ids.append(conn_dict["id"])

    # Bulk insert 10,000 sessions with invoices, lines, and debits
    total_sessions = 10000
    batch_size = 2000

    print(
        f"\n[BENCHMARK] Inserting {total_sessions} sessions across {len(cp_ids)} charge points..."
    )
    t_insert_start = perf_counter()

    for batch_idx in range(0, total_sessions, batch_size):
        sessions_data = []
        for j in range(batch_size):
            idx = batch_idx + j
            c_idx = idx % len(cp_ids)
            delta_mins = idx * 2
            sess_time = t_start + timedelta(minutes=delta_mins % (30 * 24 * 60))
            sessions_data.append(
                {
                    "charge_point_id": cp_ids[c_idx],
                    "connector_id": conn_ids[c_idx],
                    "driver_id": driver.id,
                    "tag_tail": "9999",
                    "authorization_status": "Accepted",
                    "started_at": sess_time - timedelta(minutes=30),
                    "ended_at": sess_time,
                    "energy_kwh": Decimal("15.5"),
                    "meter_start_wh": Decimal(0),
                    "meter_stop_wh": Decimal(15500),
                    "settlement_reason": "debited",
                    "settlement_completed_at": sess_time,
                    "billing_lifecycle_version": 1,
                    "release_detection": "explicit",
                    "review_reasons": [],
                }
            )

        sess_results = (
            await db_session.scalars(
                insert(ChargingSession).returning(ChargingSession.id),
                sessions_data,
            )
        ).all()

        invoices_data = []
        lines_data = []
        ledgers_data = []
        for k, s_id in enumerate(sess_results):
            inv_id = uuid4()
            sess_time = sessions_data[k]["ended_at"]
            invoices_data.append(
                {
                    "id": inv_id,
                    "session_id": s_id,
                    "driver_id": driver.id,
                    "station_id": station.id,
                    "total_vnd": 50000,
                    "rounding_rule": "round_half_up",
                    "created_at": sess_time,
                }
            )
            lines_data.append(
                {
                    "id": uuid4(),
                    "invoice_id": inv_id,
                    "line_type": "energy",
                    "local_date": sess_time.date(),
                    "started_at": sess_time - timedelta(minutes=30),
                    "ended_at": sess_time,
                    "energy_wh": Decimal(15500),
                    "rate_vnd": 3225,
                    "band_label": "BenchTier",
                    "interpolated": False,
                    "tariff_id": tariff.id,
                    "amount_vnd": 50000,
                }
            )
            ledgers_data.append(
                {
                    "wallet_id": wallet.id,
                    "entry_type": "charging_debit",
                    "amount_vnd": -50000,
                    "balance_after_vnd": 1000000 - 50000,
                    "reference_type": "charging_session",
                    "reference_id": str(s_id),
                    "created_at": sess_time,
                }
            )

        await db_session.execute(insert(Invoice).values(invoices_data))
        await db_session.execute(insert(InvoiceLine).values(lines_data))
        await db_session.execute(insert(WalletLedger).values(ledgers_data))
        await db_session.flush()

    t_insert_end = perf_counter()
    print(
        f"[BENCHMARK] Insertion of {total_sessions} sessions took {t_insert_end - t_insert_start:.2f}s."
    )

    # Refresh PostgreSQL query planner statistics after 10,000 bulk rows
    await db_session.execute(
        text(
            "ANALYZE charging_sessions; ANALYZE invoices; ANALYZE invoice_lines; ANALYZE wallet_ledger;"
        )
    )

    # Benchmark query executions
    query = RevenueReportQuery(
        period="month",
        date_from=date(2026, 11, 1),
        station_id=station.id,
        page=1,
        page_size=50,
    )

    # Warm-up run
    await get_revenue_report(db_session, query, owner_id=owner.id)

    times = []
    for run_i in range(5):
        t0 = perf_counter()
        report = await get_revenue_report(db_session, query, owner_id=owner.id)
        t1 = perf_counter()
        dur = t1 - t0
        times.append(dur)
        print(f"[BENCHMARK] Run #{run_i + 1}: {dur:.4f}s")

    times.sort()
    # 95th percentile index
    p95_idx = int(0.95 * len(times))
    p95_time = times[p95_idx]

    print(
        f"[BENCHMARK RESULT] p95 query latency: {p95_time:.4f}s for 10,000 sessions / 50 chargers"
    )
    assert report.summary.invoiced_sessions == total_sessions
    assert report.summary.total_invoice_vnd == total_sessions * 50000
    assert p95_time <= 2.0, (
        f"Expected p95 <= 2.0s, got {p95_time:.4f}s on 10,000 sessions"
    )
