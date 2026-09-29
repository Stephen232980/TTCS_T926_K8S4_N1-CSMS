from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.identity.authorization import ActorScope
from src.modules.stations.models import Station


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
