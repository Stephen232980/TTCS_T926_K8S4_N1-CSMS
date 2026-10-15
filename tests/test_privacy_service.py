from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from src.modules.identity.authorization import AuthorizationEvidence
from src.modules.identity.models import User
from src.modules.privacy.service import PrivacyRetentionService
from src.platform.audit.models import AuditLog


@pytest.fixture
def mock_db():
    db = MagicMock()
    db.scalar = AsyncMock()
    db.scalars = AsyncMock()
    db.execute = AsyncMock()
    db.get = AsyncMock()
    db.commit = AsyncMock()
    return db


@pytest.mark.asyncio
async def test_get_retention_policies(mock_db):
    mock_db.scalar.side_effect = [10, 5, 2, 1, 100, 3, 20]
    service = PrivacyRetentionService(mock_db)

    resp = await service.get_retention_policies()
    assert len(resp.policies) == 7
    assert resp.policies[0].table_name == "login_ip_attempts"
    assert resp.policies[0].eligible_count == 10
    assert resp.policies[1].table_name == "sessions"
    assert resp.policies[1].eligible_count == 5


@pytest.mark.asyncio
async def test_run_retention_cleanup(mock_db):
    # Mock rowcount returns for the 7 delete executions
    rowcounts = [4, 6, 1, 0, 50, 2, 12]
    mock_results = []
    for count in rowcounts:
        m = MagicMock()
        m.rowcount = count
        mock_results.append(m)

    mock_db.execute.side_effect = mock_results

    with patch(
        "src.modules.privacy.service.ghi_nhat_ky", new_callable=AsyncMock
    ) as mock_audit:
        service = PrivacyRetentionService(mock_db)
        result = await service.run_retention_cleanup(
            actor_id=uuid4(), permission="admin.privacy.manage"
        )

        assert result.deleted_login_attempts == 4
        assert result.deleted_expired_sessions == 6
        assert result.deleted_idempotency_keys == 1
        assert result.deleted_pending_messages == 0
        assert result.deleted_telemetry_buckets == 50
        assert result.deleted_sent_alert_emails == 2
        assert result.deleted_health_samples == 12
        assert result.total_deleted == sum(rowcounts)

        mock_audit.assert_awaited_once()
        mock_db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_check_legal_hold_with_active_charging_session(mock_db):
    user_id = uuid4()
    # First scalar query checks active charging session
    mock_db.scalar.side_effect = [1]  # session found
    service = PrivacyRetentionService(mock_db)

    is_held, reason = await service.check_legal_hold(user_id)
    assert is_held is True
    assert "phiên sạc đang hoạt động" in (reason or "")


@pytest.mark.asyncio
async def test_check_legal_hold_with_audit_flag(mock_db):
    user_id = uuid4()
    audit_entry = AuditLog(
        action="privacy.legal_hold",
        object_type="user",
        object_id=str(user_id),
        data={"hold": True, "reason": "Tranh chấp pháp lý #999"},
        occurred_at=datetime.now(UTC),
    )
    mock_db.scalar.side_effect = [None, audit_entry]
    service = PrivacyRetentionService(mock_db)

    is_held, reason = await service.check_legal_hold(user_id)
    assert is_held is True
    assert reason == "Tranh chấp pháp lý #999"


@pytest.mark.asyncio
async def test_check_legal_hold_clean_account(mock_db):
    user_id = uuid4()
    mock_db.scalar.side_effect = [None, None]
    service = PrivacyRetentionService(mock_db)

    is_held, reason = await service.check_legal_hold(user_id)
    assert is_held is False
    assert reason is None


@pytest.mark.asyncio
async def test_set_legal_hold(mock_db):
    user_id = uuid4()
    actor_id = uuid4()
    user = User(id=user_id, email="driver@test.local", status="active")
    mock_db.get.return_value = user

    with patch(
        "src.modules.privacy.service.ghi_nhat_ky", new_callable=AsyncMock
    ) as mock_audit:
        service = PrivacyRetentionService(mock_db)
        resp = await service.set_legal_hold(
            user_id=user_id,
            hold=True,
            reason="Yêu cầu kiểm toán nội bộ",
            actor_id=actor_id,
        )

        assert resp.legal_hold is True
        assert resp.reason == "Yêu cầu kiểm toán nội bộ"
        mock_audit.assert_awaited_once()
        mock_db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_set_legal_hold_on_anonymized_rejected(mock_db):
    user_id = uuid4()
    user = User(id=user_id, email="anon@deleted.local", status="anonymized")
    mock_db.get.return_value = user

    service = PrivacyRetentionService(mock_db)
    with pytest.raises(HTTPException) as exc:
        await service.set_legal_hold(
            user_id=user_id,
            hold=True,
            reason="Yêu cầu",
            actor_id=uuid4(),
        )
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_anonymize_user_invalid_confirmation_phrase(mock_db):
    service = PrivacyRetentionService(mock_db)
    with pytest.raises(HTTPException) as exc:
        await service.anonymize_user(
            user_id=uuid4(),
            actor_id=uuid4(),
            reason="Xóa dữ liệu",
            confirm_phrase="WRONG_PHRASE",
        )
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_anonymize_user_not_found(mock_db):
    mock_db.scalar.return_value = None
    service = PrivacyRetentionService(mock_db)

    with pytest.raises(HTTPException) as exc:
        await service.anonymize_user(
            user_id=uuid4(),
            actor_id=uuid4(),
            reason="Xóa tài khoản",
            confirm_phrase="CONFIRM_ANONYMIZE",
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_anonymize_user_already_anonymized(mock_db):
    uid = uuid4()
    user = User(id=uid, email="anonymized_123@deleted.local", status="anonymized")
    mock_db.scalar.return_value = user
    service = PrivacyRetentionService(mock_db)

    with pytest.raises(HTTPException) as exc:
        await service.anonymize_user(
            user_id=uid,
            actor_id=uuid4(),
            reason="Xóa",
            confirm_phrase="CONFIRM_ANONYMIZE",
        )
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_anonymize_user_admin_cannot_self_anonymize(mock_db):
    admin_id = uuid4()
    user = User(id=admin_id, email="admin@csms.local", status="active")
    mock_db.scalar.return_value = user
    service = PrivacyRetentionService(mock_db)

    with pytest.raises(HTTPException) as exc:
        await service.anonymize_user(
            user_id=admin_id,
            actor_id=admin_id,
            reason="Xóa chính mình",
            confirm_phrase="CONFIRM_ANONYMIZE",
            actor_roles=frozenset({"admin"}),
        )
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_anonymize_user_blocks_last_active_admin(mock_db):
    admin_id = uuid4()
    actor_id = uuid4()
    user = User(id=admin_id, email="admin1@csms.local", status="active")

    # 1. select User
    # 2. check is_admin -> returns "admin"
    # 3. check other admin -> returns None (no other admin)
    mock_db.scalar.side_effect = [user, "admin", None]
    service = PrivacyRetentionService(mock_db)

    with pytest.raises(HTTPException) as exc:
        await service.anonymize_user(
            user_id=admin_id,
            actor_id=actor_id,
            reason="Xóa admin",
            confirm_phrase="CONFIRM_ANONYMIZE",
            actor_roles=frozenset({"admin"}),
        )
    assert exc.value.status_code == 409
    assert "ít nhất một quản trị viên" in exc.value.detail


@pytest.mark.asyncio
async def test_anonymize_user_success_preserves_records(mock_db):
    driver_id = uuid4()
    actor_id = uuid4()
    user = User(
        id=driver_id,
        email="driver@ev-charge.vn",
        status="active",
        password_hash="SECRET_HASH",
        failed_login_count=2,
    )

    # 1. select User -> user
    # 2. check is_admin -> None (driver is not admin)
    # 3. check active charging session -> None (clean)
    # 4. check legal hold audit -> None (clean)
    # 5. count invoices -> 15
    # 6. count charging sessions -> 10
    # 7. count wallet ledger -> 22
    mock_db.scalar.side_effect = [user, None, None, None, 15, 10, 22]

    with patch(
        "src.modules.privacy.service.ghi_nhat_ky", new_callable=AsyncMock
    ) as mock_audit:
        service = PrivacyRetentionService(mock_db)
        resp = await service.anonymize_user(
            user_id=driver_id,
            actor_id=actor_id,
            reason="Yêu cầu hủy tài khoản tài xế",
            confirm_phrase="CONFIRM_ANONYMIZE",
            actor_roles=frozenset({"admin"}),
            authorization=AuthorizationEvidence(
                permission="admin.privacy.manage", roles=("admin",)
            ),
        )

        assert resp.status == "anonymized"
        assert resp.anonymized_email == f"anonymized_{driver_id.hex[:12]}@deleted.local"
        assert resp.preserved_financial_records["invoices"] == 15
        assert resp.preserved_financial_records["charging_sessions"] == 10
        assert resp.preserved_financial_records["wallet_ledger_entries"] == 22

        # User state mutated properly
        assert user.status == "anonymized"
        assert user.password_hash == "ANONYMIZED_DISABLED_PASSWORD_HASH"
        assert user.failed_login_count == 0
        assert user.email == f"anonymized_{driver_id.hex[:12]}@deleted.local"

        # Verify session revocation and role deletion executed
        assert mock_db.execute.await_count == 2
        mock_audit.assert_awaited_once()
        mock_db.commit.assert_awaited_once()
