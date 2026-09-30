import logging
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from hashlib import sha256
from uuid import UUID

from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.sql.elements import ColumnElement

from src.modules.identity.authorization import ActorScope
from src.modules.stations.exceptions import (
    ChargePointCodeAlreadyExistsError,
    ChargePointCodeLockedError,
    ChargePointOwnershipDeniedError,
    StationIdempotencyConflictError,
    StationOwnershipDeniedError,
)
from src.modules.stations.models import (
    ChargePoint,
    Connector,
    Station,
    StationCreateIdempotency,
)

_security_logger = logging.getLogger("csms.security")


def _idempotency_lock_id(actor_id: UUID, idempotency_key: UUID) -> int:
    digest = sha256(actor_id.bytes + idempotency_key.bytes).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=True)


@dataclass(frozen=True)
class StationPage:
    items: list[Station]
    total: int


@dataclass(frozen=True)
class ChargePointPage:
    items: list[ChargePoint]
    total: int


def _build_station_conditions(
    scope: ActorScope,
    *,
    status: str | None,
    search: str | None,
) -> list[ColumnElement[bool]]:
    conditions: list[ColumnElement[bool]] = []

    if scope.owner_id is not None:
        conditions.append(Station.owner_id == scope.owner_id)

    if status is not None:
        conditions.append(Station.status == status)

    normalized_search = search.strip() if search is not None else ""
    if normalized_search:
        pattern = f"%{normalized_search}%"
        conditions.append(
            or_(
                Station.name.ilike(pattern),
                Station.address.ilike(pattern),
            )
        )

    return conditions


class StationRepository:
    def __init__(self, db_session: AsyncSession) -> None:
        self._db_session = db_session

    async def list_stations(
        self,
        scope: ActorScope,
    ) -> list[Station]:
        conditions = _build_station_conditions(
            scope,
            status=None,
            search=None,
        )
        statement = select(Station).where(*conditions)
        result = await self._db_session.execute(statement)
        return list(result.scalars().all())

    async def list_stations_page(
        self,
        scope: ActorScope,
        *,
        page: int,
        page_size: int,
        status: str | None,
        search: str | None,
    ) -> StationPage:
        conditions = _build_station_conditions(
            scope,
            status=status,
            search=search,
        )
        offset = (page - 1) * page_size

        items_statement = (
            select(Station)
            .where(*conditions)
            .order_by(
                Station.created_at.desc(),
                Station.id.asc(),
            )
            .offset(offset)
            .limit(page_size)
        )
        count_statement = (
            select(func.count(Station.id)).select_from(Station).where(*conditions)
        )

        items_result = await self._db_session.execute(items_statement)
        total = await self._db_session.scalar(count_statement)

        return StationPage(
            items=list(items_result.scalars().all()),
            total=total or 0,
        )

    async def create_station(
        self,
        *,
        owner_id: UUID,
        name: str,
        address: str,
        latitude: Decimal,
        longitude: Decimal,
    ) -> Station:
        station = Station(
            owner_id=owner_id,
            name=name,
            address=address,
            latitude=latitude,
            longitude=longitude,
        )
        self._db_session.add(station)
        await self._db_session.flush()
        await self._db_session.refresh(station)
        return station

    async def is_charge_point_code_available(
        self,
        code: str,
        *,
        excluding_charge_point_id: UUID | None = None,
    ) -> bool:
        normalized_code = code.strip()
        statement = select(ChargePoint.id).where(
            func.lower(ChargePoint.code) == normalized_code.lower()
        )
        if excluding_charge_point_id is not None:
            statement = statement.where(
                ChargePoint.id != excluding_charge_point_id,
            )
        charge_point_id = await self._db_session.scalar(statement.limit(1))
        return charge_point_id is None

    async def create_charge_point(
        self,
        station_id: UUID,
        scope: ActorScope,
        *,
        code: str,
        connector_count: int,
    ) -> ChargePoint | None:
        station = await self.get_station_by_id(station_id, scope)
        if station is None:
            return None

        if not await self.is_charge_point_code_available(code):
            raise ChargePointCodeAlreadyExistsError

        charge_point = ChargePoint(
            station_id=station.id,
            code=code.strip(),
            connectors=[
                Connector(connector_number=connector_number)
                for connector_number in range(1, connector_count + 1)
            ],
        )
        self._db_session.add(charge_point)

        try:
            await self._db_session.flush()
        except IntegrityError as error:
            constraint_name = getattr(
                getattr(error.orig, "diag", None),
                "constraint_name",
                None,
            )
            if constraint_name in {
                "ix_charge_points_code",
                "uq_charge_points_code_ci",
            }:
                raise ChargePointCodeAlreadyExistsError from error
            raise

        await self._db_session.refresh(charge_point)
        await self._db_session.refresh(
            charge_point,
            attribute_names=["connectors"],
        )
        return charge_point

    async def list_charge_points_page(
        self,
        station_id: UUID,
        scope: ActorScope,
        *,
        page: int,
        page_size: int,
    ) -> ChargePointPage | None:
        station = await self.get_station_by_id(station_id, scope)
        if station is None:
            return None

        offset = (page - 1) * page_size
        items_statement = (
            select(ChargePoint)
            .where(ChargePoint.station_id == station.id)
            .options(selectinload(ChargePoint.connectors))
            .order_by(
                ChargePoint.created_at.desc(),
                ChargePoint.id.asc(),
            )
            .offset(offset)
            .limit(page_size)
        )
        count_statement = (
            select(func.count(ChargePoint.id))
            .select_from(ChargePoint)
            .where(ChargePoint.station_id == station.id)
        )

        items_result = await self._db_session.execute(items_statement)
        total = await self._db_session.scalar(count_statement)
        return ChargePointPage(
            items=list(items_result.scalars().all()),
            total=total or 0,
        )

    async def update_charge_point_code(
        self,
        charge_point_id: UUID,
        scope: ActorScope,
        *,
        code: str,
    ) -> ChargePoint | None:
        statement = (
            select(ChargePoint)
            .join(Station, Station.id == ChargePoint.station_id)
            .where(ChargePoint.id == charge_point_id)
            .with_for_update()
        )
        if scope.owner_id is not None:
            statement = statement.where(Station.owner_id == scope.owner_id)

        charge_point = await self._db_session.scalar(statement)
        if charge_point is None:
            existing_charge_point_id = await self._db_session.scalar(
                select(ChargePoint.id).where(ChargePoint.id == charge_point_id)
            )
            if existing_charge_point_id is None or scope.owner_id is None:
                return None
            _security_logger.warning(
                "cross_owner_charge_point_access_denied actor_id=%s charge_point_id=%s",
                scope.actor_id,
                charge_point_id,
            )
            raise ChargePointOwnershipDeniedError

        if charge_point.code_locked_at is not None:
            raise ChargePointCodeLockedError

        normalized_code = code.strip()
        if not await self.is_charge_point_code_available(
            normalized_code,
            excluding_charge_point_id=charge_point.id,
        ):
            raise ChargePointCodeAlreadyExistsError

        charge_point.code = normalized_code
        try:
            await self._db_session.flush()
        except IntegrityError as error:
            constraint_name = getattr(
                getattr(error.orig, "diag", None),
                "constraint_name",
                None,
            )
            if constraint_name in {
                "ix_charge_points_code",
                "uq_charge_points_code_ci",
            }:
                raise ChargePointCodeAlreadyExistsError from error
            if constraint_name == "ck_charge_points_code_locked":
                raise ChargePointCodeLockedError from error
            raise

        await self._db_session.refresh(charge_point)
        await self._db_session.refresh(
            charge_point,
            attribute_names=["connectors"],
        )
        return charge_point

    async def lock_charge_point_code_for_charging(
        self,
        charge_point_id: UUID,
        *,
        locked_at: datetime,
    ) -> None:
        await self._db_session.execute(
            update(ChargePoint)
            .where(ChargePoint.id == charge_point_id)
            .where(ChargePoint.code_locked_at.is_(None))
            .values(code_locked_at=locked_at)
        )

    async def create_station_idempotent(
        self,
        *,
        actor_id: UUID,
        idempotency_key: UUID,
        request_hash: str,
        name: str,
        address: str,
        latitude: Decimal,
        longitude: Decimal,
    ) -> Station:
        await self._db_session.execute(
            select(
                func.pg_advisory_xact_lock(
                    _idempotency_lock_id(actor_id, idempotency_key)
                )
            )
        )

        idempotency_record = await self._db_session.scalar(
            select(StationCreateIdempotency).where(
                StationCreateIdempotency.actor_id == actor_id,
                StationCreateIdempotency.idempotency_key == idempotency_key,
            )
        )

        if idempotency_record is not None:
            if idempotency_record.request_hash != request_hash:
                raise StationIdempotencyConflictError

            station = await self._db_session.scalar(
                select(Station).where(
                    Station.id == idempotency_record.station_id,
                )
            )
            if station is None:
                raise RuntimeError("Idempotency record references a missing station")
            return station

        station = await self.create_station(
            owner_id=actor_id,
            name=name,
            address=address,
            latitude=latitude,
            longitude=longitude,
        )
        self._db_session.add(
            StationCreateIdempotency(
                actor_id=actor_id,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                station_id=station.id,
            )
        )
        await self._db_session.flush()
        return station

    async def get_station_by_id(
        self,
        station_id: UUID,
        scope: ActorScope,
    ) -> Station | None:
        statement = select(Station).where(Station.id == station_id)

        if scope.owner_id is not None:
            statement = statement.where(Station.owner_id == scope.owner_id)

        station = await self._db_session.scalar(statement)

        if station is not None or scope.owner_id is None:
            return station

        existing_station_id = await self._db_session.scalar(
            select(Station.id).where(Station.id == station_id)
        )
        if existing_station_id is None:
            return None

        _security_logger.warning(
            "cross_owner_station_access_denied actor_id=%s station_id=%s",
            scope.actor_id,
            station_id,
        )
        raise StationOwnershipDeniedError

    async def update_station(
        self,
        station_id: UUID,
        scope: ActorScope,
        *,
        name: str | None,
        address: str | None,
        latitude: Decimal | None,
        longitude: Decimal | None,
    ) -> Station | None:
        station = await self.get_station_by_id(station_id, scope)
        if station is None:
            return None

        if name is not None:
            station.name = name
        if address is not None:
            station.address = address
        if latitude is not None:
            station.latitude = latitude
        if longitude is not None:
            station.longitude = longitude

        await self._db_session.flush()
        await self._db_session.refresh(station)
        return station
