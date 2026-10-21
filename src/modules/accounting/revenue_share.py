"""Partner revenue sharing based on settled invoice energy and idle lines."""

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID

from sqlalchemy import String, and_, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.accounting.models import PartnerContract
from src.modules.billing.models import Invoice, InvoiceLine
from src.modules.charging.models import ChargingSession
from src.modules.stations.models import Station
from src.modules.wallet.models import Wallet, WalletLedger

BASIS_POINTS = 10_000


@dataclass(frozen=True)
class RevenueShareDay:
    station_id: UUID
    local_date: date
    contract_id: UUID | None
    owner_id: UUID | None
    owner_share_bps: int | None
    energy_vnd: int
    idle_vnd: int
    owner_share_vnd: int
    partner_share_vnd: int
    unallocated_vnd: int


@dataclass
class _RevenueAmounts:
    owner_id: UUID | None
    owner_share_bps: int | None
    energy_vnd: int = 0
    idle_vnd: int = 0


async def create_partner_contract(
    db: AsyncSession,
    *,
    station_id: UUID,
    owner_share_bps: int,
    effective_from: date,
    effective_to: date | None = None,
) -> PartnerContract:
    """Create an inclusive-dated contract, rejecting overlapping station terms."""
    if not 0 <= owner_share_bps <= BASIS_POINTS:
        raise ValueError("owner_share_bps must be between 0 and 10000")
    if effective_to is not None and effective_to < effective_from:
        raise ValueError("effective_to must not precede effective_from")

    station = await db.scalar(
        select(Station).where(Station.id == station_id).with_for_update()
    )
    if station is None:
        raise LookupError(f"Station {station_id} does not exist")

    overlap_conditions = [
        PartnerContract.station_id == station_id,
        or_(
            PartnerContract.effective_to.is_(None),
            PartnerContract.effective_to >= effective_from,
        ),
    ]
    if effective_to is not None:
        overlap_conditions.append(PartnerContract.effective_from <= effective_to)
    overlaps = await db.scalar(
        select(PartnerContract.id).where(*overlap_conditions).limit(1)
    )
    if overlaps is not None:
        raise ValueError("Partner contract dates overlap an existing station contract")

    contract = PartnerContract(
        station_id=station.id,
        owner_id=station.owner_id,
        owner_share_bps=owner_share_bps,
        effective_from=effective_from,
        effective_to=effective_to,
    )
    db.add(contract)
    await db.flush()
    return contract


async def calculate_partner_revenue_share(
    db: AsyncSession,
    *,
    date_from: date,
    date_to: date,
    station_id: UUID | None = None,
) -> list[RevenueShareDay]:
    """Calculate settled energy/idle revenue by effective contract and local day.

    Settled debits must have exactly one matching wallet ledger entry. Zero
    invoices are accepted as successfully settled but contribute no revenue.
    Legacy-exempt and unsettled invoices are not shareable.
    """
    if date_from > date_to:
        raise ValueError("date_from must not be after date_to")

    debit_count = (
        select(func.count(WalletLedger.id))
        .select_from(WalletLedger)
        .join(Wallet, Wallet.id == WalletLedger.wallet_id)
        .where(
            Wallet.driver_id == Invoice.driver_id,
            WalletLedger.entry_type == "charging_debit",
            WalletLedger.reference_type == "charging_session",
            WalletLedger.reference_id == cast(ChargingSession.id, String),
            WalletLedger.amount_vnd == -Invoice.total_vnd,
        )
        .correlate(Invoice, ChargingSession)
        .scalar_subquery()
    )
    statement = (
        select(
            InvoiceLine.id,
            Station.id,
            InvoiceLine.local_date,
            InvoiceLine.line_type,
            InvoiceLine.amount_vnd,
            PartnerContract.id,
            PartnerContract.owner_id,
            PartnerContract.owner_share_bps,
        )
        .select_from(InvoiceLine)
        .join(Invoice, Invoice.id == InvoiceLine.invoice_id)
        .join(ChargingSession, ChargingSession.id == Invoice.session_id)
        .join(Station, Station.id == Invoice.station_id)
        .outerjoin(
            PartnerContract,
            and_(
                PartnerContract.station_id == Station.id,
                PartnerContract.effective_from <= InvoiceLine.local_date,
                or_(
                    PartnerContract.effective_to.is_(None),
                    PartnerContract.effective_to >= InvoiceLine.local_date,
                ),
            ),
        )
        .where(
            InvoiceLine.local_date >= date_from,
            InvoiceLine.local_date <= date_to,
            InvoiceLine.line_type.in_(("energy", "idle")),
            ChargingSession.settlement_completed_at.is_not(None),
            or_(
                and_(
                    ChargingSession.settlement_reason == "debited",
                    Invoice.total_vnd > 0,
                    debit_count == 1,
                ),
                and_(
                    ChargingSession.settlement_reason == "zero_invoice",
                    Invoice.total_vnd == 0,
                ),
            ),
        )
        .order_by(Station.id, InvoiceLine.local_date, InvoiceLine.id)
    )
    if station_id is not None:
        statement = statement.where(Station.id == station_id)

    rows = (await db.execute(statement)).all()
    contracts_by_line: dict[UUID, set[UUID]] = {}
    amounts: dict[tuple[UUID, date, UUID | None], _RevenueAmounts] = {}
    for (
        line_id,
        row_station_id,
        local_date,
        line_type,
        amount_vnd,
        contract_id,
        owner_id,
        owner_share_bps,
    ) in rows:
        if contract_id is not None:
            line_contracts = contracts_by_line.setdefault(line_id, set())
            line_contracts.add(contract_id)
            if len(line_contracts) > 1:
                raise ValueError(
                    f"Overlapping partner contracts cover invoice line {line_id}"
                )

        key = (row_station_id, local_date, contract_id)
        item = amounts.setdefault(
            key,
            _RevenueAmounts(
                owner_id=owner_id,
                owner_share_bps=owner_share_bps,
            ),
        )
        if line_type == "energy":
            item.energy_vnd += amount_vnd
        else:
            item.idle_vnd += amount_vnd

    results: list[RevenueShareDay] = []
    for (row_station_id, local_date, result_contract_id), item in amounts.items():
        gross_vnd = item.energy_vnd + item.idle_vnd
        if result_contract_id is None:
            owner_share_vnd = 0
            partner_share_vnd = 0
            unallocated_vnd = gross_vnd
        else:
            if item.owner_id is None or item.owner_share_bps is None:
                raise ValueError(
                    f"Partner contract {result_contract_id} has incomplete terms"
                )
            owner_share_vnd = int(
                (Decimal(gross_vnd * item.owner_share_bps) / BASIS_POINTS).quantize(
                    Decimal(1), rounding=ROUND_HALF_UP
                )
            )
            partner_share_vnd = gross_vnd - owner_share_vnd
            unallocated_vnd = 0
        results.append(
            RevenueShareDay(
                station_id=row_station_id,
                local_date=local_date,
                contract_id=result_contract_id,
                owner_id=item.owner_id,
                owner_share_bps=item.owner_share_bps,
                energy_vnd=item.energy_vnd,
                idle_vnd=item.idle_vnd,
                owner_share_vnd=owner_share_vnd,
                partner_share_vnd=partner_share_vnd,
                unallocated_vnd=unallocated_vnd,
            )
        )
    return results
