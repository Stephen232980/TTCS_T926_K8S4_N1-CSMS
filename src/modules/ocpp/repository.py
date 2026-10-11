"""Read charger registration for S-06 before accepting a WebSocket."""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.stations.models import ChargePoint, Station


@dataclass(frozen=True, slots=True)
class RegisteredChargePoint:
    charge_point_id: UUID
    station_id: UUID
    station_status: str


class OcppRegistrationRepository:
    def __init__(self, db_session: AsyncSession) -> None:
        self._db_session = db_session

    async def get_registered_charge_point(
        self,
        charge_point_code: str,
    ) -> RegisteredChargePoint | None:
        """S-06: find a non-archived charger and its current station status."""
        statement = (
            select(ChargePoint.id, ChargePoint.station_id, Station.status)
            .join(Station, Station.id == ChargePoint.station_id)
            .where(
                func.lower(ChargePoint.code) == charge_point_code,
                ChargePoint.archived_at.is_(None),
                Station.archived_at.is_(None),
            )
        )
        result = await self._db_session.execute(statement)
        row = result.one_or_none()
        if row is None:
            return None

        charge_point_id, station_id, station_status = row
        return RegisteredChargePoint(
            charge_point_id=charge_point_id,
            station_id=station_id,
            station_status=station_status,
        )
