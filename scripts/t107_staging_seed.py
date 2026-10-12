"""T-107 isolated staging fixture: 20 virtual chargers, drivers, cards, wallets.

Default invocation is a plan-only dry run. Database writes require --apply or
--cleanup and an explicit test-environment acknowledgement. Never use on prod.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import secrets
import selectors
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from scripts.t107_tariff_seed import Plan, ensure_first_tariff
from src.modules.charging.models import ChargingCard, ChargingSession
from src.modules.charging.service import tag_hash
from src.modules.identity.authorization import AuthorizationEvidence
from src.modules.identity.models import Role, User, UserRole
from src.modules.identity.role_assignment import assign_user_roles
from src.modules.identity.security import hash_password
from src.modules.stations.models import ChargePoint, Connector, Station
from src.modules.wallet.eligibility import du_so_du_de_sac
from src.modules.wallet.manual_topup import ManualTopupRequest, nap_tay
from src.modules.wallet.models import Wallet, WalletLedger
from src.modules.wallet.provisioning import ensure_driver_wallet

DRIVER_COUNT = 20
OWNER_EMAIL = "t107-seed-owner@example.com"
STATION_NAME = "T107-STAGING-VIRTUAL-STATION"
STATION_ADDRESS = "T107-STAGING-SEED; virtual station; do not use for real charging"
RECEIPT_PREFIX = "T107-SEED-"


@dataclass(frozen=True)
class FixtureConfig:
    """Explicit test prices/credit; business values must be approved by the team."""

    plan: Plan
    amount_vnd: int

    def validate(self) -> None:
        self.plan.bands()
        if type(self.amount_vnd) is not int or not 0 < self.amount_vnd <= 2**63 - 1:
            raise ValueError("Initial wallet amount must be a positive integer VND")


def driver_email(index: int) -> str:
    _index(index)
    return f"t107-seed-driver-{index:03d}@example.com"


def charger_code(index: int) -> str:
    _index(index)
    return f"T107-{index:03d}"


def card_tag(index: int) -> str:
    _index(index)
    return f"T107TAG-{index:03d}"


def receipt_code(index: int) -> str:
    _index(index)
    return f"{RECEIPT_PREFIX}{index:03d}"


def _index(index: int) -> None:
    if type(index) is not int or not 1 <= index <= DRIVER_COUNT:
        raise ValueError("T-107 fixture index must be 1..20")


async def _role(session: AsyncSession, code: str) -> None:
    if await session.scalar(select(Role.id).where(Role.code == code)) is None:
        raise RuntimeError(f"Required role {code} is missing; run base migrations/seed")


async def _seed_user(session: AsyncSession, email: str, roles: tuple[str, ...]) -> User:
    """Create new test-only identity, or validate an existing fixture identity.

    Never reset credentials, reactivate disabled accounts or change their roles.
    The caller must verify the associated station/card on existing identities.
    """
    user = await session.scalar(
        select(User).where(User.email == email).with_for_update()
    )
    if user is not None:
        if user.status != "active":
            raise RuntimeError(
                f"Fixture identity {email} is not active (possibly cleaned)"
            )
        assigned = set(
            (
                await session.scalars(
                    select(Role.code).join(UserRole).where(UserRole.user_id == user.id)
                )
            ).all()
        )
        if not set(roles) <= assigned:
            raise RuntimeError(f"Fixture identity {email} has unexpected roles")
        return user
    user = User(
        email=email,
        password_hash=hash_password(secrets.token_urlsafe(32)),
        status="active",
    )
    session.add(user)
    await session.flush()
    await assign_user_roles(session, user.id, roles, replace=False)
    return user


async def _seed_station(session: AsyncSession, owner: User) -> Station:
    stations = (
        await session.scalars(
            select(Station).where(Station.name == STATION_NAME).with_for_update()
        )
    ).all()
    if len(stations) > 1:
        raise RuntimeError("Ambiguous T107 station name; refusing to proceed")
    if stations:
        station = stations[0]
        if (
            station.owner_id != owner.id
            or station.address != STATION_ADDRESS
            or station.archived_at is not None
            or station.status != "active"
        ):
            raise RuntimeError("T107 station ownership/status marker mismatch")
        return station
    station = Station(
        owner_id=owner.id,
        name=STATION_NAME,
        address=STATION_ADDRESS,
        latitude=Decimal("10.000000"),
        longitude=Decimal("106.000000"),
        status="active",
    )
    session.add(station)
    await session.flush()
    return station


async def _seed_charger(session: AsyncSession, station: Station, index: int) -> None:
    code = charger_code(index)
    charger = await session.scalar(select(ChargePoint).where(ChargePoint.code == code))
    name = f"T107 virtual charger {code}"
    if charger is None:
        charger = ChargePoint(station_id=station.id, code=code, name=name)
        session.add(charger)
        await session.flush()
    elif (
        charger.station_id != station.id
        or charger.name != name
        or charger.archived_at is not None
    ):
        raise RuntimeError(f"Refusing to take over charger {code}")
    connector = await session.scalar(
        select(Connector).where(
            Connector.charge_point_id == charger.id, Connector.connector_number == 1
        )
    )
    if connector is None:
        session.add(Connector(charge_point_id=charger.id, connector_number=1))
        await session.flush()
    elif connector.archived_at is not None:
        raise RuntimeError(f"Fixture connector {code} has been archived")


async def _seed_card(
    session: AsyncSession, driver: User, owner: User, index: int, *, existed: bool
) -> None:
    tag = card_tag(index)
    card = await session.scalar(
        select(ChargingCard).where(ChargingCard.tag_hash == tag_hash(tag))
    )
    if card is None:
        if existed:
            raise RuntimeError(f"Existing {driver.email} lacks fixture card")
        session.add(
            ChargingCard(
                tag_hash=tag_hash(tag),
                tag_tail=tag[-4:],
                driver_id=driver.id,
                issuer_id=owner.id,
                status="active",
            )
        )
        await session.flush()
    elif (
        card.driver_id != driver.id
        or card.issuer_id != owner.id
        or card.status != "active"
        or card.expires_at is not None
    ):
        raise RuntimeError(f"Refusing to reuse an altered tag {tag}")


async def _credit_once(
    session: AsyncSession,
    *,
    driver: User,
    wallet: Wallet,
    admin: User,
    index: int,
    amount_vnd: int,
) -> bool:
    """T-88 issues an auditable manual receipt once; never refill on reruns."""
    receipt = receipt_code(index)
    ledger = await session.scalar(
        select(WalletLedger).where(
            WalletLedger.entry_type == "manual_topup",
            WalletLedger.reference_id == receipt,
        )
    )
    if ledger is not None:
        if (
            ledger.wallet_id != wallet.id
            or ledger.amount_vnd != amount_vnd
            or ledger.reference_type != "manual_topup"
        ):
            raise RuntimeError(f"Conflicting existing receipt {receipt}")
        return False
    if wallet.status != "active" or wallet.balance_vnd != 0:
        raise RuntimeError(
            f"Refusing to seed nonempty/locked wallet for {driver.email}"
        )
    admin_roles = tuple(
        sorted(
            (
                await session.scalars(
                    select(Role.code).join(UserRole).where(UserRole.user_id == admin.id)
                )
            ).all()
        )
    )
    if "admin" not in admin_roles:
        raise RuntimeError("Administrator roles changed before T-88 topup")
    await nap_tay(
        session,
        driver_id=driver.id,
        actor_id=admin.id,
        request=ManualTopupRequest(amount_vnd=amount_vnd, receipt_code=receipt),
        authorization=AuthorizationEvidence(
            permission="admin.wallet.manual_topup", roles=admin_roles
        ),
    )
    return True


async def _admin(session: AsyncSession, email: str) -> User:
    if not email or email.lower().startswith("t107-"):
        raise ValueError("Specify an existing non-fixture admin email")
    admin = await session.scalar(select(User).where(User.email == email.lower()))
    if admin is None or admin.status != "active":
        raise RuntimeError("Specified administrator does not exist or is disabled")
    role = await session.scalar(
        select(Role.id)
        .join(UserRole)
        .where(UserRole.user_id == admin.id, Role.code == "admin")
    )
    if role is None:
        raise RuntimeError("Specified account does not have the admin role")
    return admin


async def seed_fixture(
    session: AsyncSession, *, config: FixtureConfig, admin_email: str
) -> tuple[UUID, int]:
    """Atomic when called within session.begin(); returns station ID/new receipts."""
    config.validate()
    # Serialize T107 operations, including cleanup, across concurrent workers.
    await session.execute(text("SELECT pg_advisory_xact_lock(1070026011)"))
    for role in ("driver", "operator", "station_owner"):
        await _role(session, role)
    admin = await _admin(session, admin_email)
    original_owner = await session.scalar(
        select(User.id).where(User.email == OWNER_EMAIL)
    )
    owner = await _seed_user(session, OWNER_EMAIL, ("station_owner", "operator"))
    if original_owner is not None:
        marker = await session.scalar(
            select(Station.id).where(
                Station.name == STATION_NAME,
                Station.owner_id == owner.id,
                Station.address == STATION_ADDRESS,
            )
        )
        if marker is None:
            raise RuntimeError("Existing T107 owner has no valid fixture station")
    station = await _seed_station(session, owner)
    await ensure_first_tariff(session, station_id=station.id, plan=config.plan)
    new_receipts = 0
    for index in range(1, DRIVER_COUNT + 1):
        await _seed_charger(session, station, index)
        email = driver_email(index)
        existed = (
            await session.scalar(select(User.id).where(User.email == email)) is not None
        )
        driver = await _seed_user(session, email, ("driver",))
        await _seed_card(session, driver, owner, index, existed=existed)
        wallet = await ensure_driver_wallet(session, driver.id)
        if await _credit_once(
            session,
            driver=driver,
            wallet=wallet,
            admin=admin,
            index=index,
            amount_vnd=config.amount_vnd,
        ):
            new_receipts += 1
            eligibility = await du_so_du_de_sac(
                session, driver_id=driver.id, station_id=station.id
            )
            if not eligibility.allowed:
                raise RuntimeError(
                    f"Initial funding does not satisfy eligibility for {driver.email}: "
                    f"{eligibility.reason}"
                )
    return station.id, new_receipts


async def cleanup_fixture(session: AsyncSession) -> int:
    """One-command logical cleanup: retain ledger, audit and billing evidence.

    Abort on unexpected ownership, live sessions or incomplete fixture. No
    deletes; accounts/cards disabled, station and chargers archived.
    """
    await session.execute(text("SELECT pg_advisory_xact_lock(1070026011)"))
    owner = await session.scalar(
        select(User).where(User.email == OWNER_EMAIL).with_for_update()
    )
    if owner is None:
        return 0  # Already absent on a new database.
    station = await session.scalar(
        select(Station)
        .where(
            Station.name == STATION_NAME,
            Station.owner_id == owner.id,
            Station.address == STATION_ADDRESS,
        )
        .with_for_update()
    )
    if station is None:
        raise RuntimeError("Cannot verify ownership of T107 fixture station")
    drivers: list[User] = []
    cards: list[ChargingCard] = []
    chargers: list[ChargePoint] = []
    connectors: list[Connector] = []
    for index in range(1, DRIVER_COUNT + 1):
        email, code = driver_email(index), charger_code(index)
        driver = await session.scalar(
            select(User).where(User.email == email).with_for_update()
        )
        charger = await session.scalar(
            select(ChargePoint).where(ChargePoint.code == code)
        )
        card = await session.scalar(
            select(ChargingCard).where(
                ChargingCard.tag_hash == tag_hash(card_tag(index))
            )
        )
        if (
            driver is None
            or charger is None
            or card is None
            or card.driver_id != driver.id
            or card.issuer_id != owner.id
            or charger.station_id != station.id
            or charger.name != f"T107 virtual charger {code}"
        ):
            raise RuntimeError(f"T107 fixture ownership mismatch at index {index}")
        connector = await session.scalar(
            select(Connector).where(
                Connector.charge_point_id == charger.id, Connector.connector_number == 1
            )
        )
        if connector is None:
            raise RuntimeError(f"T107 connector missing at index {index}")
        # Role assignment also provisions a private virtual charging card for
        # every driver. Validate both cards before disabling either one.
        driver_cards = (
            await session.scalars(
                select(ChargingCard)
                .where(ChargingCard.driver_id == driver.id)
                .with_for_update()
            )
        ).all()
        automatic = [
            candidate
            for candidate in driver_cards
            if candidate.issuer_id == driver.id and candidate.id != card.id
        ]
        if (
            len(driver_cards) != 2
            or len(automatic) != 1
            or sum(candidate.id == card.id for candidate in driver_cards) != 1
        ):
            raise RuntimeError(
                f"Unexpected card inventory for {email}; manual review required"
            )
        drivers.append(driver)
        cards.extend(driver_cards)
        chargers.append(charger)
        connectors.append(connector)
    charger_ids = [c.id for c in chargers]
    unsettled = await session.scalar(
        select(func.count())
        .select_from(ChargingSession)
        .where(
            ChargingSession.charge_point_id.in_(charger_ids),
            (
                ChargingSession.ended_at.is_(None)
                | ChargingSession.settlement_completed_at.is_(None)
            ),
        )
    )
    if unsettled:
        raise RuntimeError(
            "T107 sessions are open/unsettled: close and settle before cleanup"
        )
    if station.archived_at is not None:
        # An idempotent cleanup must not alter an already-cleaned fixture.
        if (
            owner.status != "deactivated"
            or any(d.status != "deactivated" for d in drivers)
            or any(c.status != "blocked" for c in cards)
        ):
            raise RuntimeError("Partially cleaned fixture requires manual review")
        return 0
    now = datetime.now(UTC)
    for card in cards:
        card.status = "blocked"
    for driver in drivers:
        driver.status = "deactivated"
    for connector in connectors:
        connector.archived_at = now
    for charger in chargers:
        charger.archived_at = now
    station.status = "inactive"
    station.archived_at = now
    owner.status = "deactivated"
    return DRIVER_COUNT


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="T107 isolated virtual staging data")
    action = parser.add_mutually_exclusive_group()
    action.add_argument(
        "--apply", action="store_true", help="Seed fixtures into test DB"
    )
    action.add_argument(
        "--cleanup", action="store_true", help="Logically deactivate fixtures"
    )
    parser.add_argument("--admin-email", help="Existing active admin; only for --apply")
    parser.add_argument("--boundaries", nargs=2, type=int, metavar=("MIN1", "MIN2"))
    parser.add_argument("--rates", nargs=3, type=int, metavar=("R1", "R2", "R3"))
    parser.add_argument("--amount-vnd", type=int)
    parser.add_argument("--confirm-test-environment", action="store_true")
    return parser.parse_args()


async def main() -> None:
    args = arguments()
    if args.apply or args.cleanup:
        raise SystemExit(
            "Legacy T-107 fixed fixture is disabled for CLI writes. "
            "Use scripts.t107_manifest_run with a T-108 run manifest instead."
        )
    if args.cleanup:
        if any(
            (args.admin_email, args.boundaries, args.rates, args.amount_vnd is not None)
        ):
            raise SystemExit("Cleanup does not take seed parameters")
    else:
        if args.boundaries is None or args.rates is None or args.amount_vnd is None:
            raise SystemExit("Specify --boundaries, --rates and --amount-vnd")
        config = FixtureConfig(
            Plan(args.boundaries[0], args.boundaries[1], tuple(args.rates)),
            args.amount_vnd,
        )
        config.validate()
        for band in config.plan.bands():
            print(
                f"{band.start_min:04d}-{band.end_min:04d}: "
                f"{band.energy_rate_vnd_per_kwh} VND/kWh"
            )
        print(
            f"20 virtual chargers/cards/drivers/wallets, "
            f"{config.amount_vnd} VND per wallet"
        )
        if not args.apply:
            print("DRY RUN: no DB connection or changes; add --apply for test DB only")
            return
        if not args.admin_email:
            raise SystemExit("--admin-email is required for --apply")
    if (
        not args.confirm_test_environment
        or os.environ.get("T107_ALLOW_STAGING_SEED") != "YES"
    ):
        raise SystemExit(
            "Database write blocked: set T107_ALLOW_STAGING_SEED=YES and supply "
            "--confirm-test-environment only after verifying the isolated test DB"
        )
    from src.platform.database.session import SessionFactory

    async with SessionFactory() as session, session.begin():
        if args.cleanup:
            count = await cleanup_fixture(session)
            print(
                f"T107 cleanup: disabled {count} drivers, "
                "retained all financial evidence"
            )
        else:
            station_id, new_receipts = await seed_fixture(
                session, config=config, admin_email=args.admin_email
            )
            print(f"T107 station {station_id}; new T88 receipts: {new_receipts}/20")


if __name__ == "__main__":
    asyncio.run(
        main(),
        loop_factory=lambda: asyncio.SelectorEventLoop(selectors.SelectSelector()),
    )
