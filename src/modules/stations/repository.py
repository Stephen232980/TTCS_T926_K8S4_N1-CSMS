import logging
from dataclasses import dataclass
from decimal import Decimal
from hashlib import sha256
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from src.modules.identity.authorization import ActorScope
from src.modules.stations.exceptions import (
    StationIdempotencyConflictError,
    StationOwnershipDeniedError,
)
from src.modules.stations.models import Station, StationCreateIdempotency

_security_logger = logging.getLogger("csms.security")


def _idempotency_lock_id(actor_id: UUID, idempotency_key: UUID) -> int:
    digest = sha256(actor_id.bytes + idempotency_key.bytes).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=True)


@dataclass(frozen=True)
class StationPage:
    items: list[Station]
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
