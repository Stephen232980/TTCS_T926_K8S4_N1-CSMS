"""T-104 read-only eligibility snapshot; callers own their transaction.

This does not reserve money or authorize a charging session. T-105 must recheck
at the relevant start/authorization boundary rather than cache this result.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import get_settings
from src.modules.pricing.models import TariffBand
from src.modules.pricing.service import lay_bieu_gia_hieu_luc
from src.modules.wallet.models import Wallet

EligibilityReason = Literal[
    "wallet_low", "wallet_missing", "wallet_locked", "tariff_unavailable"
]


@dataclass(frozen=True, slots=True)
class ChargingEligibility:
    allowed: bool
    reason: EligibilityReason | None
    balance_vnd: int | None
    minimum_balance_vnd: int | None
    tariff_id: UUID | None


async def du_so_du_de_sac(
    session: AsyncSession,
    *,
    driver_id: UUID,
    station_id: UUID,
    now: datetime | None = None,
) -> ChargingEligibility:
    """Use highest effective band rate, or reserve only without a tariff.

    Missing/locked wallets and malformed tariffs fail closed. No wallet is
    created and no balance, ledger, or transaction boundary is modified.
    An unknown station raises T-68's TariffNotFoundError.
    """
    tariff = await lay_bieu_gia_hieu_luc(
        session,
        station_id=station_id,
        ngay=now if now is not None else datetime.now(UTC),
    )
    wallet = await session.scalar(
        select(Wallet)
        .where(Wallet.driver_id == driver_id)
        .execution_options(populate_existing=True)
    )
    balance = wallet.balance_vnd if wallet is not None else None
    config = get_settings()
    if tariff is None:
        minimum = config.wallet_reserve_vnd
    else:
        highest_rate = await session.scalar(
            select(func.max(TariffBand.energy_rate_vnd_per_kwh)).where(
                TariffBand.tariff_id == tariff.id
            )
        )
        if highest_rate is None:
            return ChargingEligibility(
                False, "tariff_unavailable", balance, None, tariff.id
            )
        minimum = config.charging_minimum_kwh * highest_rate
    tariff_id = tariff.id if tariff is not None else None
    if wallet is None:
        return ChargingEligibility(False, "wallet_missing", None, minimum, tariff_id)
    if wallet.status != "active":
        return ChargingEligibility(False, "wallet_locked", balance, minimum, tariff_id)
    allowed = wallet.balance_vnd >= 0 and wallet.balance_vnd >= minimum
    return ChargingEligibility(
        allowed, None if allowed else "wallet_low", balance, minimum, tariff_id
    )
