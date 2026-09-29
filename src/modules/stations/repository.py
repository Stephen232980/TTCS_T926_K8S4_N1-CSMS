import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.identity.authorization import ActorScope
from src.modules.stations.exceptions import StationOwnershipDeniedError
from src.modules.stations.models import Station

_security_logger = logging.getLogger("csms.security")


class StationRepository:
    def __init__(self, db_session: AsyncSession) -> None:
        self._db_session = db_session

    async def list_stations(
        self,
        scope: ActorScope,
    ) -> list[Station]:
        statement = select(Station)

        if scope.owner_id is not None:
            statement = statement.where(Station.owner_id == scope.owner_id)

        result = await self._db_session.execute(statement)
        return list(result.scalars().all())

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
