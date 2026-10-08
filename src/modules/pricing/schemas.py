"""T-61 tariff request and explicit snapshot responses."""

from datetime import date, datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

Money = Annotated[int, Field(strict=True, ge=0, le=2**63 - 1)]


class FlatTariffCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    effective_from: date
    energy_rate_vnd_per_kwh: Money
    idle_rate_vnd_per_minute: Money
    grace_minutes: int = Field(strict=True, ge=0, le=2**31 - 1)
    label: str = Field(default="Cả ngày", min_length=1, max_length=100)

    @field_validator("effective_from", mode="before")
    @classmethod
    def calendar_date_only(cls, value: object) -> object:
        if type(value) is date:
            return value
        if isinstance(value, str):
            try:
                parsed = date.fromisoformat(value)
            except ValueError:
                pass
            else:
                if parsed.isoformat() == value:
                    return parsed
        raise ValueError("Ngày hiệu lực phải có dạng YYYY-MM-DD")


class TariffBandResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    start_min: int
    end_min: int
    energy_rate_vnd_per_kwh: int
    label: str


class TariffResponse(BaseModel):
    id: UUID
    station_id: UUID
    effective_from: date
    idle_rate_vnd_per_minute: int
    grace_minutes: int
    created_at: datetime
    bands: list[TariffBandResponse]
