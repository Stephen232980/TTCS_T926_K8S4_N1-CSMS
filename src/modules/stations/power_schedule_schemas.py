"""Pydantic schemas for station power limit schedules (S-45 / G2)."""

from datetime import date, datetime
from decimal import Decimal
from typing import Self
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from src.modules.stations.power_bands import PowerBandInput


def _parse_time_to_minute(time_str: str) -> int:
    """Parse 'HH:MM' or 'HH:MM:SS' string to minute of day [0, 1440]."""
    parts = time_str.strip().split(":")
    if len(parts) not in (2, 3):
        raise ValueError(f"Định dạng giờ không hợp lệ: '{time_str}'. Dùng 'HH:MM'")
    hour = int(parts[0])
    minute = int(parts[1])
    if hour == 24 and minute == 0:
        return 1440
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"Giờ không hợp lệ: '{time_str}'")
    return hour * 60 + minute


def _minute_to_time(minute: int) -> str:
    """Format minute of day to 'HH:MM'."""
    h = minute // 60
    m = minute % 60
    return f"{h:02d}:{m:02d}"


class PowerScheduleBandInput(BaseModel):
    start_time: str = Field(description="Giờ bắt đầu 'HH:MM'")
    end_time: str = Field(description="Giờ kết thúc 'HH:MM'")
    power_limit_kw: Decimal = Field(
        gt=0, description="Hạn mức công suất tính bằng kW (phải > 0)"
    )

    def to_band_input(self) -> PowerBandInput:
        start_min = _parse_time_to_minute(self.start_time)
        end_min = _parse_time_to_minute(self.end_time)
        power_limit_w = round(self.power_limit_kw * Decimal(1000))
        return PowerBandInput(
            start_min=start_min,
            end_min=end_min,
            power_limit_w=power_limit_w,
        )


class PowerScheduleBandDisplay(BaseModel):
    id: UUID | None = None
    start_min: int
    end_min: int
    start_time: str
    end_time: str
    power_limit_w: int
    power_limit_kw: str


class PowerScheduleSaveRequest(BaseModel):
    effective_from: date = Field(description="Ngày bắt đầu hiệu lực (YYYY-MM-DD)")
    bands: list[PowerScheduleBandInput] = Field(
        min_length=1, description="Danh sách các khung giờ công suất"
    )

    @model_validator(mode="after")
    def validate_inputs(self) -> Self:
        for b in self.bands:
            _parse_time_to_minute(b.start_time)
            _parse_time_to_minute(b.end_time)
        return self


class PowerScheduleResponse(BaseModel):
    id: UUID
    station_id: UUID
    effective_from: date
    created_at: datetime
    updated_at: datetime
    bands: list[PowerScheduleBandDisplay]


class CurrentPowerLimitResponse(BaseModel):
    station_id: UUID
    timezone: str
    local_time: str
    local_date: date
    power_limit_w: int | None
    power_limit_kw: str | None
    scheduled_limit_w: int | None = None
    scheduled_limit_kw: str | None = None
    applied_limit_w: int | None = None
    applied_limit_kw: str | None = None
    confirmed_limit_w: int | None = None
    confirmed_limit_kw: str | None = None
    compliance_status: str = "unconfigured"
    state: str | None = None
    issue: str | None = None
