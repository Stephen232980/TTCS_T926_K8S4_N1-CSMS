"""Request and response contracts for monthly station subscriptions."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.modules.pricing.schemas import TariffBandCreateRequest

Money = Annotated[int, Field(strict=True, gt=0, le=2**63 - 1)]


class SubscriptionPlanCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=100)
    monthly_fee_vnd: Money
    bands: list[TariffBandCreateRequest] = Field(min_length=1, max_length=1440)

    @field_validator("name")
    @classmethod
    def nonempty_name(cls, value: str) -> str:
        if not value:
            raise ValueError("Tên gói không được để trống")
        return value


class SubscriptionBandResponse(BaseModel):
    start_min: int
    end_min: int
    energy_rate_vnd_per_kwh: str
    label: str


class SubscriptionPlanResponse(BaseModel):
    id: UUID
    station_id: UUID
    station_name: str
    name: str
    monthly_fee_vnd: str
    active: bool
    bands: list[SubscriptionBandResponse]


class DriverSubscriptionResponse(BaseModel):
    id: UUID
    station_id: UUID
    station_name: str
    plan_id: UUID
    plan_name: str
    monthly_fee_vnd: str
    status: str
    current_period_start: datetime
    current_period_end: datetime
    next_billing_at: datetime | None
