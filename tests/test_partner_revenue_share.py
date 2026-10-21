from datetime import date, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.accounting.revenue_share import (
    calculate_partner_revenue_share,
    create_partner_contract,
)
from src.modules.billing.models import Invoice, InvoiceLine
from src.modules.charging.models import ChargingSession
from src.modules.identity.models import User
from src.modules.pricing.models import Tariff
from src.modules.stations.models import ChargePoint, Connector, Station
from src.modules.wallet.models import Wallet, WalletLedger

REPORT_TIMEZONE = ZoneInfo("Asia/Ho_Chi_Minh")


async def _build_test_environment(
    db_session: AsyncSession,
) -> tuple[User, User, Wallet, Station, ChargePoint, Connector, Tariff]:
    owner = User(email=f"owner-{uuid4()}@example.com", password_hash="test")
    driver = User(email=f"driver-{uuid4()}@example.com", password_hash="test")
    db_session.add_all([owner, driver])
    await db_session.flush()

    wallet = Wallet(driver_id=driver.id, balance_vnd=1_000_000, status="active")
    db_session.add(wallet)
    station = Station(
        owner_id=owner.id,
        name=f"Station-{uuid4()}"[:30],
        address="123 Vo Van Kiet, TP.HCM",
        latitude=Decimal("10.7769"),
        longitude=Decimal("106.7009"),
        status="active",
        timezone="Asia/Ho_Chi_Minh",
    )
    db_session.add(station)
    await db_session.flush()

    charge_point = ChargePoint(station_id=station.id, code=f"CP-{uuid4()}"[:20])
    db_session.add(charge_point)
    await db_session.flush()
    connector = Connector(
        charge_point_id=charge_point.id,
        connector_number=1,
        status="Available",
    )
    tariff = Tariff(
        station_id=station.id,
        effective_from=date(2026, 1, 1),
        idle_rate_vnd_per_minute=1000,
        grace_minutes=15,
    )
    db_session.add_all([connector, tariff])
    await db_session.flush()
    return owner, driver, wallet, station, charge_point, connector, tariff


async def _add_invoice_line(
    db_session: AsyncSession,
    *,
    invoice: Invoice,
    tariff_id: UUID,
    local_date: date,
    line_type: str,
    amount_vnd: int,
) -> None:
    started_at = datetime.combine(local_date, datetime.min.time(), REPORT_TIMEZONE)
    db_session.add(
        InvoiceLine(
            invoice_id=invoice.id,
            line_type=line_type,
            local_date=local_date,
            started_at=started_at,
            ended_at=started_at + timedelta(minutes=1),
            energy_wh=Decimal(0) if line_type == "idle" else Decimal(1),
            rate_vnd=amount_vnd,
            band_label=f"{line_type}-{uuid4()}",
            interpolated=False,
            tariff_id=tariff_id,
            amount_vnd=amount_vnd,
        )
    )


@pytest.mark.asyncio
async def test_revenue_share_uses_effective_dates_and_only_settled_energy_idle(
    db_session: AsyncSession,
) -> None:
    (
        owner,
        driver,
        wallet,
        station,
        charge_point,
        connector,
        tariff,
    ) = await _build_test_environment(db_session)

    october_contract = await create_partner_contract(
        db_session,
        station_id=station.id,
        owner_share_bps=5000,
        effective_from=date(2026, 10, 1),
        effective_to=date(2026, 10, 31),
    )
    november_contract = await create_partner_contract(
        db_session,
        station_id=station.id,
        owner_share_bps=2500,
        effective_from=date(2026, 11, 1),
    )
    assert october_contract.owner_id == owner.id
    assert november_contract.owner_id == owner.id

    settled_at = datetime(2026, 11, 2, 12, 0, tzinfo=REPORT_TIMEZONE)
    charging = ChargingSession(
        charge_point_id=charge_point.id,
        connector_id=connector.id,
        driver_id=driver.id,
        tag_tail="9999",
        authorization_status="Accepted",
        started_at=settled_at - timedelta(hours=1),
        ended_at=settled_at - timedelta(minutes=10),
        meter_start_wh=Decimal(0),
        meter_stop_wh=Decimal(10),
        energy_kwh=Decimal("0.01"),
        settlement_reason="debited",
        settlement_completed_at=settled_at,
    )
    db_session.add(charging)
    await db_session.flush()

    invoice = Invoice(
        session_id=charging.id,
        driver_id=driver.id,
        station_id=station.id,
        total_vnd=16,
        rounding_rule="round_half_up",
    )
    db_session.add(invoice)
    await db_session.flush()
    await _add_invoice_line(
        db_session,
        invoice=invoice,
        tariff_id=tariff.id,
        local_date=date(2026, 9, 30),
        line_type="energy",
        amount_vnd=1,
    )
    await _add_invoice_line(
        db_session,
        invoice=invoice,
        tariff_id=tariff.id,
        local_date=date(2026, 10, 31),
        line_type="energy",
        amount_vnd=3,
    )
    await _add_invoice_line(
        db_session,
        invoice=invoice,
        tariff_id=tariff.id,
        local_date=date(2026, 10, 31),
        line_type="idle",
        amount_vnd=2,
    )
    await _add_invoice_line(
        db_session,
        invoice=invoice,
        tariff_id=tariff.id,
        local_date=date(2026, 11, 1),
        line_type="energy",
        amount_vnd=5,
    )
    await _add_invoice_line(
        db_session,
        invoice=invoice,
        tariff_id=tariff.id,
        local_date=date(2026, 11, 1),
        line_type="idle",
        amount_vnd=5,
    )
    db_session.add(
        WalletLedger(
            wallet_id=wallet.id,
            entry_type="charging_debit",
            amount_vnd=-invoice.total_vnd,
            balance_after_vnd=wallet.balance_vnd - invoice.total_vnd,
            reference_type="charging_session",
            reference_id=str(charging.id),
            created_at=settled_at,
        )
    )
    await db_session.flush()

    # These invoices must not leak into the share: one is unsettled, one exempt.
    unsettled = ChargingSession(
        charge_point_id=charge_point.id,
        connector_id=connector.id,
        driver_id=driver.id,
        tag_tail="9999",
        authorization_status="Accepted",
        started_at=settled_at,
        ended_at=settled_at + timedelta(minutes=1),
        meter_start_wh=Decimal(0),
        meter_stop_wh=Decimal(1),
        energy_kwh=Decimal("0.001"),
    )
    exempt = ChargingSession(
        charge_point_id=charge_point.id,
        connector_id=connector.id,
        driver_id=driver.id,
        tag_tail="9999",
        authorization_status="Accepted",
        started_at=settled_at + timedelta(minutes=2),
        ended_at=settled_at + timedelta(minutes=3),
        meter_start_wh=Decimal(0),
        meter_stop_wh=Decimal(1),
        energy_kwh=Decimal("0.001"),
        settlement_reason="legacy_exempt",
        settlement_completed_at=settled_at,
    )
    missing_ledger = ChargingSession(
        charge_point_id=charge_point.id,
        connector_id=connector.id,
        driver_id=driver.id,
        tag_tail="9999",
        authorization_status="Accepted",
        started_at=settled_at + timedelta(minutes=4),
        ended_at=settled_at + timedelta(minutes=5),
        meter_start_wh=Decimal(0),
        meter_stop_wh=Decimal(1),
        energy_kwh=Decimal("0.001"),
        settlement_reason="debited",
        settlement_completed_at=settled_at,
    )
    db_session.add_all([unsettled, exempt, missing_ledger])
    await db_session.flush()
    for session, total in (
        (unsettled, 100),
        (exempt, 200),
        (missing_ledger, 300),
    ):
        separate_invoice = Invoice(
            session_id=session.id,
            driver_id=driver.id,
            station_id=station.id,
            total_vnd=total,
            rounding_rule="round_half_up",
        )
        db_session.add(separate_invoice)
        await db_session.flush()
        await _add_invoice_line(
            db_session,
            invoice=separate_invoice,
            tariff_id=tariff.id,
            local_date=date(2026, 10, 31),
            line_type="energy",
            amount_vnd=total,
        )
    await db_session.flush()

    rows = await calculate_partner_revenue_share(
        db_session,
        date_from=date(2026, 9, 30),
        date_to=date(2026, 11, 1),
        station_id=station.id,
    )
    rows_by_date = {row.local_date: row for row in rows}
    assert set(rows_by_date) == {
        date(2026, 9, 30),
        date(2026, 10, 31),
        date(2026, 11, 1),
    }

    uncontracted = rows_by_date[date(2026, 9, 30)]
    assert uncontracted.contract_id is None
    assert uncontracted.unallocated_vnd == 1
    assert uncontracted.owner_share_vnd == uncontracted.partner_share_vnd == 0

    october = rows_by_date[date(2026, 10, 31)]
    assert october.contract_id == october_contract.id
    assert october.owner_share_bps == 5000
    assert (october.energy_vnd, october.idle_vnd) == (3, 2)
    assert (october.owner_share_vnd, october.partner_share_vnd) == (3, 2)

    november = rows_by_date[date(2026, 11, 1)]
    assert november.contract_id == november_contract.id
    assert november.owner_share_bps == 2500
    assert (november.energy_vnd, november.idle_vnd) == (5, 5)
    assert (november.owner_share_vnd, november.partner_share_vnd) == (3, 7)


@pytest.mark.asyncio
@pytest.mark.parametrize("owner_share_bps", [-1, 10001])
async def test_partner_contract_rejects_invalid_owner_share(
    db_session: AsyncSession, owner_share_bps: int
) -> None:
    *_, station, _, _, _ = await _build_test_environment(db_session)
    with pytest.raises(ValueError, match="between 0 and 10000"):
        await create_partner_contract(
            db_session,
            station_id=station.id,
            owner_share_bps=owner_share_bps,
            effective_from=date(2026, 1, 1),
        )


@pytest.mark.asyncio
async def test_partner_contract_rejects_overlapping_or_reversed_dates(
    db_session: AsyncSession,
) -> None:
    *_, station, _, _, _ = await _build_test_environment(db_session)
    await create_partner_contract(
        db_session,
        station_id=station.id,
        owner_share_bps=5000,
        effective_from=date(2026, 1, 1),
        effective_to=date(2026, 1, 31),
    )

    with pytest.raises(ValueError, match="overlap"):
        await create_partner_contract(
            db_session,
            station_id=station.id,
            owner_share_bps=6000,
            effective_from=date(2026, 1, 31),
        )
    with pytest.raises(ValueError, match="must not precede"):
        await create_partner_contract(
            db_session,
            station_id=station.id,
            owner_share_bps=6000,
            effective_from=date(2026, 2, 1),
            effective_to=date(2026, 1, 31),
        )
