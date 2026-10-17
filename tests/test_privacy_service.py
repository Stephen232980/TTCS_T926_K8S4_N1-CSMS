from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

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
    with patch(
        "src.modules.privacy.service.ghi_nhat_ky", new_callable=AsyncMock
    ) as audit:
        result = await PrivacyRetentionService(mock_db).run_retention_cleanup(
            actor_id=uuid4()
        )
        assert result.total_deleted == 0
        mock_db.execute.assert_not_awaited()
        assert audit.await_args.kwargs["action"] == "system.retention_cleanup_blocked"
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
    mock_db.scalar.return_value = user

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
    mock_db.scalar.return_value = user

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
async def test_legacy_anonymize_is_blocked_without_any_mutation(mock_db):
    service = PrivacyRetentionService(mock_db)
    with pytest.raises(HTTPException) as error:
        await service.anonymize_user(
            user_id=uuid4(),
            actor_id=uuid4(),
            reason="User request",
            confirm_phrase="CONFIRM_ANONYMIZE",
        )
    assert error.value.status_code == 409
    assert "privacy_execution_unavailable" in error.value.detail
    mock_db.execute.assert_not_awaited()
    mock_db.commit.assert_not_awaited()
