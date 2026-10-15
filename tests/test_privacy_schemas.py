from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from src.modules.privacy.schemas import (
    AnonymizeUserRequest,
    AnonymizeUserResponse,
    DriverPrivacyRequest,
    LegalHoldRequest,
    LegalHoldResponse,
    RetentionCleanupResponse,
    RetentionPoliciesResponse,
    RetentionPolicyItem,
)


def test_retention_policy_item_valid():
    item = RetentionPolicyItem(
        table_name="login_ip_attempts",
        policy_type="Khóa IP",
        retention_threshold="30 ngày",
        description="Dọn dẹp đăng nhập lỗi",
        eligible_count=15,
    )
    assert item.table_name == "login_ip_attempts"
    assert item.eligible_count == 15


def test_retention_policy_item_negative_count_rejected():
    with pytest.raises(ValidationError):
        RetentionPolicyItem(
            table_name="login_ip_attempts",
            policy_type="Khóa IP",
            retention_threshold="30 ngày",
            description="Dọn dẹp đăng nhập lỗi",
            eligible_count=-1,
        )


def test_retention_policies_response():
    resp = RetentionPoliciesResponse(
        policies=[
            RetentionPolicyItem(
                table_name="sessions",
                policy_type="Phiên",
                retention_threshold="7 ngày",
                description="Phiên thu hồi",
                eligible_count=5,
            )
        ],
        auto_cleanup_interval_seconds=86400,
        checked_at=datetime.now(UTC),
    )
    assert len(resp.policies) == 1
    assert resp.auto_cleanup_interval_seconds == 86400


def test_retention_cleanup_response_fields():
    now = datetime.now(UTC)
    cleanup = RetentionCleanupResponse(
        executed_at=now,
        deleted_login_attempts=2,
        deleted_expired_sessions=3,
        deleted_idempotency_keys=1,
        deleted_pending_messages=0,
        deleted_telemetry_buckets=10,
        deleted_sent_alert_emails=4,
        deleted_health_samples=8,
        total_deleted=28,
    )
    assert cleanup.total_deleted == 28
    assert cleanup.deleted_telemetry_buckets == 10


def test_anonymize_user_request():
    req = AnonymizeUserRequest(
        reason="Yêu cầu theo quyền riêng tư",
        confirm_phrase="CONFIRM_ANONYMIZE",
    )
    assert req.reason == "Yêu cầu theo quyền riêng tư"
    assert req.confirm_phrase == "CONFIRM_ANONYMIZE"

    # Too short reason
    with pytest.raises(ValidationError):
        AnonymizeUserRequest(reason="ab", confirm_phrase="CONFIRM_ANONYMIZE")


def test_anonymize_user_response():
    uid = uuid4()
    now = datetime.now(UTC)
    resp = AnonymizeUserResponse(
        user_id=uid,
        anonymized_email=f"anonymized_{uid.hex[:12]}@deleted.local",
        status="anonymized",
        anonymized_at=now,
        preserved_financial_records={"invoices": 12, "charging_sessions": 8},
    )
    assert resp.status == "anonymized"
    assert resp.preserved_financial_records["invoices"] == 12


def test_legal_hold_request():
    req = LegalHoldRequest(hold=True, reason="Đang tranh chấp hóa đơn #1234")
    assert req.hold is True
    assert req.reason == "Đang tranh chấp hóa đơn #1234"


def test_legal_hold_response():
    uid = uuid4()
    now = datetime.now(UTC)
    resp = LegalHoldResponse(
        user_id=uid, legal_hold=True, reason="Tranh chấp", updated_at=now
    )
    assert resp.user_id == uid
    assert resp.legal_hold is True
    assert resp.reason == "Tranh chấp"


def test_driver_privacy_request():
    req_empty = DriverPrivacyRequest()
    assert req_empty.reason is None

    req_with_reason = DriverPrivacyRequest(reason="Không còn sử dụng dịch vụ")
    assert req_with_reason.reason == "Không còn sử dụng dịch vụ"
