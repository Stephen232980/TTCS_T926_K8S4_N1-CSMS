from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class RetentionPolicyItem(BaseModel):
    table_name: str = Field(description="Tên bảng dữ liệu")
    policy_type: str = Field(description="Loại dữ liệu")
    retention_threshold: str = Field(description="Ngưỡng lưu trữ tối đa")
    description: str = Field(description="Mô tả chính sách dọn dẹp")
    eligible_count: int = Field(
        default=0, ge=0, description="Số lượng bản ghi đủ điều kiện dọn"
    )


class RetentionPoliciesResponse(BaseModel):
    policies: list[RetentionPolicyItem]
    auto_cleanup_interval_seconds: int
    checked_at: datetime


class RetentionCleanupResponse(BaseModel):
    executed_at: datetime
    deleted_login_attempts: int = Field(default=0, ge=0)
    deleted_expired_sessions: int = Field(default=0, ge=0)
    deleted_idempotency_keys: int = Field(default=0, ge=0)
    deleted_pending_messages: int = Field(default=0, ge=0)
    deleted_telemetry_buckets: int = Field(default=0, ge=0)
    deleted_sent_alert_emails: int = Field(default=0, ge=0)
    deleted_health_samples: int = Field(default=0, ge=0)
    total_deleted: int = Field(default=0, ge=0)


class AnonymizeUserRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=500, description="Lý do ẩn danh hóa")
    confirm_phrase: str = Field(
        description="Xác nhận ẩn danh hóa (nhập CONFIRM_ANONYMIZE)"
    )


class AnonymizeUserResponse(BaseModel):
    user_id: UUID
    anonymized_email: str
    status: str
    anonymized_at: datetime
    preserved_financial_records: dict[str, int] = Field(
        default_factory=dict,
        description="Số lượng bản ghi tài chính được bảo toàn nguyên vẹn",
    )


class LegalHoldRequest(BaseModel):
    hold: bool = Field(description="Bật hoặc tắt trạng thái tạm giữ pháp lý")
    reason: str = Field(
        min_length=3, max_length=500, description="Lý do tạm giữ/gỡ tạm giữ"
    )


class LegalHoldResponse(BaseModel):
    user_id: UUID
    legal_hold: bool
    reason: str | None = None
    updated_at: datetime


class DriverPrivacyRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=500)
