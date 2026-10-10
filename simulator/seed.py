"""S-26: seed dữ liệu trụ, đầu nối và thẻ chỉ dành cho bộ simulator."""

from __future__ import annotations

import asyncio
import os
from decimal import Decimal
from typing import cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from simulator.config import SimulatorSettings, load_settings
from src.modules.charging.models import ChargingCard
from src.modules.charging.service import tag_hash
from src.modules.identity.models import Role, User
from src.modules.identity.role_assignment import assign_user_roles
from src.modules.identity.security import hash_password
from src.modules.stations.models import ChargePoint, Connector, Station
from src.platform.database.session import SessionFactory

SIMULATOR_OPERATOR_EMAIL = "simulator.operator@example.com"


async def seed_simulator_data(settings: SimulatorSettings) -> None:
    """Create or update only the S-26 namespaced data required by the fleet."""
    password = os.environ.get("SIMULATOR_OPERATOR_PASSWORD", "")
    if not password:
        raise ValueError("SIMULATOR_OPERATOR_PASSWORD must not be empty")
    async with SessionFactory() as session, session.begin():
        operator_role = await _role(session, "operator")
        driver_role = await _role(session, "driver")
        operator = await _user(
            session,
            SIMULATOR_OPERATOR_EMAIL,
            password,
        )
        await _assign_role(session, operator, operator_role)
        station = await _station(session, operator, settings)
        for index in range(1, settings.count + 1):
            charger = await _charger(session, station, settings.code_for(index))
            await _connector(session, charger)
            driver = await _user(
                session,
                f"simulator-driver-{index:03d}@example.com",
                "simulator-driver-only",
            )
            await _assign_role(session, driver, driver_role)
            await _card(session, driver, operator, settings.tag_for(index))


async def _role(session: AsyncSession, code: str) -> Role:
    role = cast(
        Role | None,
        await session.scalar(select(Role).where(Role.code == code)),
    )
    if role is None:
        role = Role(code=code)
        session.add(role)
        await session.flush()
    return role


async def _user(session: AsyncSession, email: str, password: str) -> User:
    user = cast(
        User | None,
        await session.scalar(select(User).where(User.email == email)),
    )
    if user is None:
        user = User(
            email=email,
            password_hash=hash_password(password),
            status="active",
            balance=1000000,  # Đã thêm số dư để qua được lỗi Insufficient Balance
        )
        session.add(user)
        await session.flush()
    else:
        user.password_hash = hash_password(password)
        user.status = "active"
        user.balance = 1000000  # Cập nhật số dư nếu tài khoản đã tồn tại từ trước
    return user


async def _assign_role(session: AsyncSession, user: User, role: Role) -> None:
    await assign_user_roles(session, user.id, [role.code], replace=False)


async def _station(
    session: AsyncSession, operator: User, settings: SimulatorSettings
) -> Station:
    first_code = settings.code_for(1)
    station = cast(
        Station | None,
        await session.scalar(
            select(Station)
            .join(ChargePoint, ChargePoint.station_id == Station.id)
            .where(ChargePoint.code == first_code)
        ),
    )
    if station is None:
        station = Station(
            owner_id=operator.id,
            name=f"S-26 Simulator {settings.code_prefix}",
            address="Compose/CI virtual fleet",
            latitude=Decimal("10.000000"),
            longitude=Decimal("106.000000"),
            status="active",
        )
        session.add(station)
        await session.flush()
    else:
        station.owner_id = operator.id
        station.status = "active"
        station.archived_at = None
    return station


async def _charger(session: AsyncSession, station: Station, code: str) -> ChargePoint:
    charger = cast(
        ChargePoint | None,
        await session.scalar(select(ChargePoint).where(ChargePoint.code == code)),
    )
    if charger is None:
        charger = ChargePoint(
            station_id=station.id,
            code=code,
            name=f"S-26 virtual charger {code}",
        )
        session.add(charger)
        await session.flush()
    else:
        charger.station_id = station.id
        charger.archived_at = None
    return charger


async def _connector(session: AsyncSession, charger: ChargePoint) -> None:
    connector = await session.scalar(
        select(Connector).where(
            Connector.charge_point_id == charger.id,
            Connector.connector_number == 1,
        )
    )
    if connector is None:
        session.add(Connector(charge_point_id=charger.id, connector_number=1))


async def _card(session: AsyncSession, driver: User, operator: User, tag: str) -> None:
    card = await session.scalar(
        select(ChargingCard).where(ChargingCard.tag_hash == tag_hash(tag))
    )
    if card is None:
        card = ChargingCard(
            tag_hash=tag_hash(tag),
            tag_tail=tag[-4:],
            driver_id=driver.id,
            issuer_id=operator.id,
        )
        session.add(card)
    else:
        card.driver_id = driver.id
        card.issuer_id = operator.id
        card.status = "active"
        card.expires_at = None


async def main() -> None:
    """Seed data for the configured number of simulator chargers."""
    settings = load_settings()
    await seed_simulator_data(settings)
    print(
        f"S-26 seeded {settings.count} charger(s) with prefix {settings.code_prefix}",
        flush=True,
    )


if __name__ == "__main__":
    asyncio.run(main())
