"""T-61 tariff request and explicit snapshot responses."""

from datetime import date, datetime
from typing import Annotated, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.modules.pricing.bands import BandInput

Money = Annotated[int, Field(strict=True, ge=0, le=2**63 - 1)]


class TariffCreateFields(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    effective_from: date
    idle_rate_vnd_per_minute: Money
    grace_minutes: int = Field(strict=True, ge=0, le=2**31 - 1)

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


class FlatTariffCreateRequest(TariffCreateFields):
    energy_rate_vnd_per_kwh: Money
    label: str = Field(default="Cả ngày", min_length=1, max_length=100)


class TariffBandCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    start_min: int = Field(strict=True, ge=0, lt=1440)
    end_min: int = Field(strict=True, ge=0, le=1440)
    energy_rate_vnd_per_kwh: Money
    label: str = Field(default="", max_length=100)


class TariffCreateRequest(TariffCreateFields):
    """Accept the T-61 flat body or T-66 bands, never both."""

    energy_rate_vnd_per_kwh: Money | None = None
    label: str = Field(default="Cả ngày", min_length=1, max_length=100)
    bands: list[TariffBandCreateRequest] | None = Field(
        default=None, min_length=1, max_length=1440
    )

    @model_validator(mode="after")
    def exactly_one_price_form(self) -> Self:
        if self.bands is not None:
            if (
                "energy_rate_vnd_per_kwh" in self.model_fields_set
                or "label" in self.model_fields_set
            ):
                raise ValueError(
                    "Khi dùng bands, đơn giá và nhãn phải đặt trong từng khung"
                )
        elif self.energy_rate_vnd_per_kwh is None:
            raise ValueError("Cần energy_rate_vnd_per_kwh hoặc danh sách bands")
        return self

    def band_inputs(self) -> list[BandInput]:
        if self.bands is not None:
            return [
                BandInput(b.start_min, b.end_min, b.energy_rate_vnd_per_kwh, b.label)
                for b in self.bands
            ]
        assert self.energy_rate_vnd_per_kwh is not None
        return [BandInput(0, 1440, self.energy_rate_vnd_per_kwh, self.label)]


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
