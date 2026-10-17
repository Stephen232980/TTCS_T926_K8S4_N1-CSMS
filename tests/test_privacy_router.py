import asyncio
import selectors
from collections.abc import Iterator
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.entrypoints.http import app
from src.modules.identity.authorization import CurrentActor
from src.modules.identity.dependencies import get_current_actor
from src.modules.identity.models import User
from src.modules.privacy.schemas import (
    LegalHoldResponse,
    RetentionCleanupResponse,
    RetentionPoliciesResponse,
    RetentionPolicyItem,
)
from src.platform.database.session import get_db_session


@pytest.fixture
def client() -> Iterator[TestClient]:
    app.dependency_overrides[get_db_session] = lambda: object()

    # Route contract tests do not start charger/billing/network workers.
    test_client = TestClient(
        app,
        backend_options={
            "loop_factory": lambda: asyncio.SelectorEventLoop(
                selectors.SelectSelector()
            )
        },
    )
    try:
        yield test_client
    finally:
        test_client.close()
        app.dependency_overrides.clear()


def test_retention_policies_requires_auth(client: TestClient):
    response = client.get("/api/v1/admin/privacy/retention-policies")
    assert response.status_code == 401


def test_retention_policies_denies_driver_role(client: TestClient):
    driver_actor = CurrentActor(uuid4(), frozenset({"driver"}))
    app.dependency_overrides[get_current_actor] = lambda: driver_actor

    response = client.get("/api/v1/admin/privacy/retention-policies")
    assert response.status_code == 403


def test_retention_policies_success_for_admin(client: TestClient):
    admin_actor = CurrentActor(uuid4(), frozenset({"admin"}))
    app.dependency_overrides[get_current_actor] = lambda: admin_actor

    mock_resp = RetentionPoliciesResponse(
        policies=[
            RetentionPolicyItem(
                table_name="login_ip_attempts",
                policy_type="Khóa IP",
                retention_threshold="30 ngày",
                description="Dọn đăng nhập sai",
                eligible_count=7,
            )
        ],
        auto_cleanup_interval_seconds=86400,
        checked_at=datetime.now(UTC),
    )

    with patch(
        "src.modules.privacy.router.PrivacyRetentionService.get_retention_policies",
        new_callable=AsyncMock,
        return_value=mock_resp,
    ):
        response = client.get("/api/v1/admin/privacy/retention-policies")
        assert response.status_code == 200
        data = response.json()
        assert len(data["policies"]) == 1
        assert data["policies"][0]["table_name"] == "login_ip_attempts"
        assert data["auto_cleanup_interval_seconds"] == 86400


def test_execute_retention_cleanup_requires_admin(client: TestClient):
    # Operator role should be denied
    operator_actor = CurrentActor(uuid4(), frozenset({"operator"}))
    app.dependency_overrides[get_current_actor] = lambda: operator_actor

    response = client.post("/api/v1/admin/privacy/cleanup")
    assert response.status_code == 403


def test_execute_retention_cleanup_success_for_admin(client: TestClient):
    admin_actor = CurrentActor(uuid4(), frozenset({"admin"}))
    app.dependency_overrides[get_current_actor] = lambda: admin_actor

    mock_cleanup = RetentionCleanupResponse(
        executed_at=datetime.now(UTC),
        deleted_login_attempts=5,
        deleted_expired_sessions=2,
        deleted_idempotency_keys=1,
        deleted_pending_messages=0,
        deleted_telemetry_buckets=20,
        deleted_sent_alert_emails=3,
        deleted_health_samples=4,
        total_deleted=35,
    )

    with patch(
        "src.modules.privacy.router.PrivacyRetentionService.run_retention_cleanup",
        new_callable=AsyncMock,
        return_value=mock_cleanup,
    ):
        response = client.post("/api/v1/admin/privacy/cleanup")
        assert response.status_code == 200
        data = response.json()
        assert data["total_deleted"] == 35
        assert data["deleted_login_attempts"] == 5


def test_anonymize_user_validation_error(client: TestClient):
    admin_actor = CurrentActor(uuid4(), frozenset({"admin"}))
    app.dependency_overrides[get_current_actor] = lambda: admin_actor

    # Missing reason or confirm_phrase
    response = client.post(
        f"/api/v1/admin/privacy/anonymize/{uuid4()}",
        json={"reason": "ab", "confirm_phrase": "NO"},
    )
    assert response.status_code == 422


def test_legacy_anonymize_for_admin_is_blocked(client: TestClient):
    admin_actor = CurrentActor(uuid4(), frozenset({"admin"}))
    app.dependency_overrides[get_current_actor] = lambda: admin_actor
    response = client.post(
        f"/api/v1/admin/privacy/anonymize/{uuid4()}",
        json={
            "reason": "User request",
            "confirm_phrase": "CONFIRM_ANONYMIZE",
        },
    )
    assert response.status_code == 409
    assert "privacy_execution_unavailable" in response.json()["error"]["message"]
    assert response.headers["cache-control"] == "no-store"


def test_get_and_update_legal_hold(client: TestClient):
    target_id = uuid4()
    admin_actor = CurrentActor(uuid4(), frozenset({"admin"}))
    app.dependency_overrides[get_current_actor] = lambda: admin_actor

    # Mock DB get to return user for get_account_legal_hold
    mock_db = AsyncMock()
    mock_db.get.return_value = User(
        id=target_id, email="user@test.local", status="active"
    )
    app.dependency_overrides[get_db_session] = lambda: mock_db

    with patch(
        "src.modules.privacy.router.PrivacyRetentionService.check_legal_hold",
        new_callable=AsyncMock,
        return_value=(True, "Đang tranh chấp hóa đơn"),
    ):
        response = client.get(f"/api/v1/admin/privacy/holds/{target_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["legal_hold"] is True
        assert data["reason"] == "Đang tranh chấp hóa đơn"

    mock_hold_resp = LegalHoldResponse(
        user_id=target_id,
        legal_hold=False,
        reason=None,
        updated_at=datetime.now(UTC),
    )
    with patch(
        "src.modules.privacy.router.PrivacyRetentionService.set_legal_hold",
        new_callable=AsyncMock,
        return_value=mock_hold_resp,
    ):
        post_resp = client.post(
            f"/api/v1/admin/privacy/holds/{target_id}",
            json={"hold": False, "reason": "Tranh chấp đã được giải quyết"},
        )
        assert post_resp.status_code == 200
        assert post_resp.json()["legal_hold"] is False


def test_driver_privacy_requires_reauthentication(client: TestClient):
    actor = CurrentActor(uuid4(), frozenset({"driver"}))
    app.dependency_overrides[get_current_actor] = lambda: actor
    with patch(
        "src.modules.privacy.router.PrivacyRetentionService.anonymize_user",
        new_callable=AsyncMock,
    ) as destructive:
        response = client.post("/api/v1/driver/privacy/anonymize-request", json={})
        assert response.status_code == 422
        assert response.headers["cache-control"] == "no-store"
        destructive.assert_not_awaited()


def test_driver_request_receipt_without_anonymizing(client: TestClient):
    actor = CurrentActor(uuid4(), frozenset({"driver"}))
    app.dependency_overrides[get_current_actor] = lambda: actor
    from src.modules.privacy.schemas import PrivacyReceipt

    receipt = PrivacyReceipt(
        id=uuid4(),
        user_id=actor.user_id,
        status="pending",
        reason="Yêu cầu",
        created_at=datetime.now(UTC),
        reviewed_at=None,
        decision_reason=None,
        policy_version=None,
        blockers=["approval_required"],
    )
    with patch(
        "src.modules.privacy.router.PrivacyRetentionService.create_request",
        new_callable=AsyncMock,
        return_value=receipt,
    ) as intake:
        response = client.post(
            "/api/v1/driver/privacy/anonymize-request",
            json={"current_password": "reauth", "reason": "Yêu cầu"},
        )
        assert response.status_code == 202
        assert response.json()["status"] == "pending"
        assert response.headers["cache-control"] == "no-store"
        assert intake.await_args.kwargs["user_id"] == actor.user_id


def test_driver_can_only_query_own_requests(client: TestClient):
    actor = CurrentActor(uuid4(), frozenset({"driver"}))
    app.dependency_overrides[get_current_actor] = lambda: actor
    with patch(
        "src.modules.privacy.router.PrivacyRetentionService.list_requests",
        new_callable=AsyncMock,
        return_value=[],
    ) as read:
        assert (
            client.get(
                "/api/v1/driver/privacy/requests?user_id=" + str(uuid4())
            ).status_code
            == 200
        )
        read.assert_awaited_once_with(actor.user_id)
        assert client.get("/api/v1/admin/privacy/requests").status_code == 403
