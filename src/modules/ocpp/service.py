"""S-06 registration lookup with a short-lived database session per check."""

from src.modules.ocpp.repository import (
    OcppRegistrationRepository,
    RegisteredChargePoint,
)
from src.platform.database.session import SessionFactory


async def find_registered_charge_point(
    normalized_code: str,
) -> RegisteredChargePoint | None:
    """Look up a charger before the WebSocket upgrade is accepted."""
    async with SessionFactory() as session:
        repository = OcppRegistrationRepository(session)
        return await repository.get_registered_charge_point(normalized_code)
