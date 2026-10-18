"""Pydantic schemas for reconciliation runs and issues."""

from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

PeriodType = Literal["month", "day", "custom"]
IssueSeverity = Literal["critical", "warning", "info"]


class ReconciliationRunCreateRequest(BaseModel):
    date_from: date
    date_to: date
    station_id: UUID | None = None
    period_type: PeriodType = "month"
    note: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def validate_dates(self) -> "ReconciliationRunCreateRequest":
        if self.date_from > self.date_to:
            raise ValueError("Ngày bắt đầu phải trước hoặc bằng ngày kết thúc")
        return self


class ReconciliationIssueResponse(BaseModel):
    id: UUID
    run_id: UUID
    session_id: int
    station_id: UUID
    station_name: str
    charge_point_code: str
    connector_number: int
    driver_email: str | None
    started_at: datetime
    ended_at: datetime | None
    issue_category: str
    issue_type: str
    severity: IssueSeverity
    discrepancy_amount_vnd: str
    discrepancy_kwh: str
    billed_vnd: str | None = None
    recomputed_vnd: str | None = None
    debited_vnd: str | None = None
    money_difference_vnd: str | None = None
    meter_kwh: str | None = None
    billed_kwh: str | None = None
    kwh_difference: str | None = None
    description: str
    details: str
    evidence: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class ReconciliationRunResponse(BaseModel):
    id: UUID
    period_type: str
    date_from: date
    date_to: date
    station_id: UUID | None
    cutoff_at: datetime
    created_at: datetime
    created_by: UUID | None
    status: str
    total_sessions: int
    matched_sessions: int
    mismatch_sessions: int
    missing_data_sessions: int
    exempt_sessions: int = 0
    beginning_uncollected_invoices_vnd: str = "0"
    beginning_uncollected_count: int = 0
    total_meter_kwh: str
    total_billed_kwh: str
    kwh_discrepancy: str
    total_billed_vnd: str
    total_recomputed_vnd: str
    total_debited_vnd: str
    money_discrepancy_vnd: str
    wallet_discrepancy_vnd: str = "0"
    summary_counts: dict[str, Any]
    algorithm_version: str
    input_hash: str


class ReconciliationRunListResponse(BaseModel):
    items: list[ReconciliationRunResponse]
    total: int
    page: int
    total_pages: int


class ReconciliationIssuesListResponse(BaseModel):
    items: list[ReconciliationIssueResponse]
    total: int
    page: int
    total_pages: int
