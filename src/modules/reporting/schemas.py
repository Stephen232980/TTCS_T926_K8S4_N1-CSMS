from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

PeriodType = Literal["day", "week", "month", "custom"]


class RevenueReportQuery(BaseModel):
    period: PeriodType = "month"
    date_from: date | None = None
    date_to: date | None = None
    station_id: UUID | None = None
    charge_point_id: UUID | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=50, ge=1, le=100)

    @model_validator(mode="after")
    def validate_dates(self) -> "RevenueReportQuery":
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("Ngày bắt đầu phải trước hoặc bằng ngày kết thúc")
        if self.date_to == date.max:
            raise ValueError("Ngày kết thúc nằm ngoài phạm vi hỗ trợ")
        return self


class RevenueSummary(BaseModel):
    invoiced_sessions: int
    total_kwh: Decimal
    energy_amount_vnd: int
    idle_amount_vnd: int
    total_invoice_vnd: int
    debited_vnd: int
    awaiting_settlement_vnd: int
    unbilled_sessions: int
    unbilled_operating_kwh: Decimal


class ChargePointRevenueItem(BaseModel):
    station_id: UUID
    station_name: str
    charge_point_id: UUID
    charge_point_code: str
    sessions_count: int
    energy_kwh: Decimal
    energy_amount_vnd: int
    idle_amount_vnd: int
    total_invoice_vnd: int
    debited_vnd: int
    awaiting_settlement_vnd: int
    unbilled_sessions: int
    unbilled_operating_kwh: Decimal


class DailyRevenueItem(BaseModel):
    date: str
    sessions_count: int
    kwh: Decimal
    invoice_vnd: int
    debited_vnd: int


class PaginationMeta(BaseModel):
    page: int
    page_size: int
    total_items: int
    total_pages: int


class RevenueReportResponse(BaseModel):
    from_date: datetime
    to_date: datetime
    timezone: str = "Asia/Ho_Chi_Minh"
    summary: RevenueSummary
    charge_points: list[ChargePointRevenueItem]
    daily_timeline: list[DailyRevenueItem]
    pagination: PaginationMeta
