"""T-108 station ownership and T-107 manifest seed adapter.

All writes join the caller transaction; immutable financial records are retained.
"""

import secrets
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from simulator.t108_contract import RunManifest
from src.modules.charging.models import ChargingCard, ChargingSession
from src.modules.charging.service import tag_hash
from src.modules.identity.authorization import ActorScope, AuthorizationEvidence
from src.modules.identity.models import Role, User, UserRole
from src.modules.identity.role_assignment import assign_user_roles
from src.modules.identity.security import hash_password
from src.modules.pricing.bands import BandInput
from src.modules.pricing.creation import tao_bieu_gia
from src.modules.pricing.models import Tariff, TariffBand
from src.modules.stations.models import ChargePoint, Connector, Station
from src.modules.wallet.eligibility import du_so_du_de_sac
from src.modules.wallet.manual_topup import ManualTopupRequest, nap_tay
from src.modules.wallet.models import WalletLedger
from src.modules.wallet.provisioning import ensure_driver_wallet


def lock_key(manifest: RunManifest) -> int:
    return int(manifest.run_id.hex[:15], 16)


async def user(
    session: AsyncSession, identity: UUID, email: str, roles: list[str]
) -> User:
    existing = await session.scalar(
        select(User)
        .where(or_(User.id == identity, User.email == email))
        .with_for_update()
    )
    if existing is not None:
        assigned = set(
            await session.scalars(
                select(Role.code).join(UserRole).where(UserRole.user_id == existing.id)
            )
        )
        if (
            existing.id != identity
            or existing.email != email
            or existing.status != "active"
            or assigned != set(roles)
        ):
            raise ValueError("Fixture identity ownership/status/roles mismatch")
        return existing
    result = User(
        id=identity,
        email=email,
        status="active",
        password_hash=hash_password(secrets.token_urlsafe(32)),
    )
    session.add(result)
    await session.flush()
    await assign_user_roles(session, result.id, roles, replace=False)
    return result


async def prepare_station(session: AsyncSession, manifest: RunManifest) -> None:
    """T-108 owns fresh stations/chargers and creates one initial tariff."""
    owner = await user(
        session,
        manifest.owner_id,
        f"t108-owner-{manifest.run_id.hex}@example.com",
        ["station_owner", "operator"],
    )
    name = f"T108-{manifest.run_id.hex}"
    marker = f"T108 run {manifest.run_id}; config {manifest.configuration_hash}; virtual test only"
    station = await session.get(Station, manifest.station_id)
    if station is None:
        station = Station(
            id=manifest.station_id,
            owner_id=owner.id,
            name=name,
            address=marker,
            latitude=Decimal(10),
            longitude=Decimal(106),
            timezone=manifest.station_timezone,
            status="active",
        )
        session.add(station)
        await session.flush()
    elif (
        station.owner_id,
        station.name,
        station.address,
        station.timezone,
        station.status,
        station.archived_at,
    ) != (owner.id, name, marker, manifest.station_timezone, "active", None):
        raise ValueError("Fixture station ownership/status mismatch")
    first, second = manifest.first_boundary_minute, manifest.second_boundary_minute
    wanted = [
        (0, first, manifest.rates[0], "T108-01"),
        (first, second, manifest.rates[1], "T108-02"),
        (second, 1440, manifest.rates[2], "T108-03"),
    ]
    tariffs = list(
        await session.scalars(select(Tariff).where(Tariff.station_id == station.id))
    )
    if tariffs:
        if len(tariffs) != 1:
            raise ValueError("Fixture tariff versions have changed")
        tariff = tariffs[0]
        rows = list(
            await session.scalars(
                select(TariffBand)
                .where(TariffBand.tariff_id == tariff.id)
                .order_by(TariffBand.start_min)
            )
        )
        actual = [
            (r.start_min, r.end_min, r.energy_rate_vnd_per_kwh, r.label) for r in rows
        ]
        from zoneinfo import ZoneInfo

        if (
            actual != wanted
            or tariff.idle_rate_vnd_per_minute != 0
            or tariff.grace_minutes != 0
            or tariff.effective_from
            != manifest.started_at.astimezone(
                ZoneInfo(manifest.station_timezone)
            ).date()
        ):
            raise ValueError(
                "Fixture tariff mismatch; never overwrite an effective tariff"
            )
        if manifest.tariff_id not in {None, tariff.id}:
            raise ValueError("Manifest tariff ID mismatch")
        manifest.tariff_id = tariff.id
    else:
        if manifest.tariff_id is not None:
            raise ValueError("Manifest tariff is missing from database")
        from zoneinfo import ZoneInfo

        tariff = await tao_bieu_gia(
            session,
            scope=ActorScope(actor_id=owner.id, owner_id=owner.id),
            station_id=station.id,
            effective_from=manifest.started_at.astimezone(
                ZoneInfo(manifest.station_timezone)
            ).date(),
            idle_rate_vnd_per_minute=0,
            grace_minutes=0,
            bands=[BandInput(*row) for row in wanted],
        )
        manifest.tariff_id = tariff.id
    for participant in manifest.participants:
        charger = await session.get(ChargePoint, participant.charge_point_id)
        if charger is None:
            session.add(
                ChargePoint(
                    id=participant.charge_point_id,
                    station_id=station.id,
                    code=participant.charge_point_code,
                    name=participant.charge_point_code,
                )
            )
            await session.flush()
        elif (
            charger.station_id != station.id
            or charger.code != participant.charge_point_code
            or charger.archived_at is not None
        ):
            raise ValueError("Fixture charger mismatch")
        connector = await session.get(Connector, participant.connector_id)
        if connector is None:
            session.add(
                Connector(
                    id=participant.connector_id,
                    charge_point_id=participant.charge_point_id,
                    connector_number=1,
                )
            )
        elif (
            connector.charge_point_id != participant.charge_point_id
            or connector.connector_number != 1
            or connector.archived_at is not None
        ):
            raise ValueError("Fixture connector mismatch")
    await session.flush()


async def seed_manifest(
    session: AsyncSession, manifest: RunManifest, admin_email: str
) -> int:
    """T-107 adapter: consume manifest, fund via T-88 once per run/driver."""
    await session.execute(
        text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_key(manifest)}
    )
    admin = await session.scalar(
        select(User)
        .join(UserRole)
        .join(Role)
        .where(
            User.email == admin_email.lower(),
            User.status == "active",
            Role.code == "admin",
        )
    )
    if admin is None:
        raise ValueError("An existing active test administrator is required")
    await prepare_station(session, manifest)
    count = 0
    for participant in manifest.participants:
        driver = await user(
            session, participant.driver_id, participant.driver_email, ["driver"]
        )
        card = await session.scalar(
            select(ChargingCard).where(
                ChargingCard.tag_hash == tag_hash(participant.card_tag)
            )
        )
        if card is None:
            session.add(
                ChargingCard(
                    tag_hash=tag_hash(participant.card_tag),
                    tag_tail=participant.card_tag[-4:],
                    driver_id=driver.id,
                    issuer_id=manifest.owner_id,
                    status="active",
                )
            )
        elif (
            card.driver_id != driver.id
            or card.issuer_id != manifest.owner_id
            or card.status != "active"
            or card.expires_at is not None
        ):
            raise ValueError("Fixture card collision or altered card")
        wallet = await ensure_driver_wallet(session, driver.id)
        if participant.wallet_id not in {None, wallet.id}:
            raise ValueError("Manifest wallet ID mismatch")
        participant.wallet_id = wallet.id
        receipt = await session.scalar(
            select(WalletLedger).where(
                WalletLedger.entry_type == "manual_topup",
                WalletLedger.reference_id == participant.seed_receipt_code,
            )
        )
        if receipt is not None:
            if (
                receipt.wallet_id != wallet.id
                or receipt.amount_vnd != manifest.seed_amount_vnd
                or receipt.reference_type != "manual_topup"
            ):
                raise ValueError("Seed receipt conflicts with manifest")
        else:
            if wallet.balance_vnd != 0 or wallet.status != "active":
                raise ValueError(
                    "Never adopt or refill a nonempty/locked fixture wallet"
                )
            await nap_tay(
                session,
                driver_id=driver.id,
                actor_id=admin.id,
                request=ManualTopupRequest(
                    amount_vnd=manifest.seed_amount_vnd,
                    receipt_code=participant.seed_receipt_code,
                ),
                authorization=AuthorizationEvidence(
                    permission="admin.wallet.manual_topup", roles=("admin",)
                ),
            )
            count += 1
        if participant.balance_before_vnd is None:
            # Recover after a crash between commit and manifest save from the receipt.
            participant.balance_before_vnd = (
                receipt.balance_after_vnd if receipt is not None else wallet.balance_vnd
            )
        if participant.balance_before_vnd != manifest.seed_amount_vnd:
            raise ValueError("Unexpected fixture opening balance")
        existing = await session.scalar(
            select(ChargingSession.id).where(
                ChargingSession.charge_point_id == participant.charge_point_id
            )
        )
        if existing is None:
            eligibility = await du_so_du_de_sac(
                session,
                driver_id=driver.id,
                station_id=manifest.station_id,
                now=manifest.started_at,
            )
            if not eligibility.allowed:
                raise ValueError(f"Fixture cannot start charging: {eligibility.reason}")
    await session.flush()
    return count


async def cleanup_manifest(session: AsyncSession, manifest: RunManifest) -> None:
    """Archive exactly this run, never delete immutable financial history."""
    station = await session.get(Station, manifest.station_id, with_for_update=True)
    if (
        station is None
        or station.owner_id != manifest.owner_id
        or station.name != f"T108-{manifest.run_id.hex}"
        or station.address
        != f"T108 run {manifest.run_id}; config {manifest.configuration_hash}; virtual test only"
    ):
        raise ValueError("Cannot verify fixture station ownership")
    identities = [p.driver_id for p in manifest.participants]
    charger_ids = [p.charge_point_id for p in manifest.participants]
    unsettled = await session.scalar(
        select(func.count())
        .select_from(ChargingSession)
        .where(
            or_(
                ChargingSession.charge_point_id.in_(charger_ids),
                ChargingSession.driver_id.in_(identities),
            ),
            or_(
                ChargingSession.ended_at.is_(None),
                ChargingSession.settlement_completed_at.is_(None),
            ),
        )
    )
    if unsettled:
        raise ValueError("Cleanup blocked by open/unsettled fixture sessions")
    now = datetime.now(UTC)
    for participant in manifest.participants:
        charger = await session.get(ChargePoint, participant.charge_point_id)
        connector = await session.get(Connector, participant.connector_id)
        driver = await session.get(User, participant.driver_id)
        if (
            charger is None
            or connector is None
            or driver is None
            or charger.station_id != station.id
            or charger.code != participant.charge_point_code
            or connector.charge_point_id != charger.id
            or driver.email != participant.driver_email
        ):
            raise ValueError("Cleanup fixture ownership mismatch")
        cards = list(
            await session.scalars(
                select(ChargingCard).where(ChargingCard.driver_id == driver.id)
            )
        )
        if (
            len(cards) != 2
            or {c.issuer_id for c in cards} != {manifest.owner_id, driver.id}
            or not any(c.tag_hash == tag_hash(participant.card_tag) for c in cards)
        ):
            raise ValueError("Unexpected fixture card inventory")
        for card in cards:
            card.status = "blocked"
        driver.status = "deactivated"
        charger.archived_at = charger.archived_at or now
        connector.archived_at = connector.archived_at or now
    owner = await session.get(User, manifest.owner_id)
    if owner is None:
        raise ValueError("Fixture owner missing")
    owner.status = "deactivated"
    station.status = "inactive"
    station.archived_at = station.archived_at or now
    await session.flush()
