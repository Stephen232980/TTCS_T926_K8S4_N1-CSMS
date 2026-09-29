from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class StationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    owner_id: UUID
    name: str
    address: str
    latitude: float
    longitude: float
    status: str
    created_at: datetime
    updated_at: datetime
