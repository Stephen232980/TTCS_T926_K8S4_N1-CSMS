import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.exc import OperationalError

from src.modules.privacy.schemas import RetentionCleanupResponse
from src.modules.privacy.worker import (
    retention_cleanup_loop,
    run_scheduled_retention_cleanup,
)


@pytest.mark.asyncio
async def test_run_scheduled_retention_cleanup_success():
    mock_resp = RetentionCleanupResponse(
        executed_at=asyncio.get_event_loop().time(),  # will be converted by pydantic or mock
        total_deleted=42,
    )

    with (
        patch("src.modules.privacy.worker.SessionFactory") as mock_session_factory,
        patch("src.modules.privacy.worker.PrivacyRetentionService") as mock_service_cls,
    ):
        mock_session = AsyncMock()
        mock_session_factory.return_value.__aenter__.return_value = mock_session

        mock_service = AsyncMock()
        mock_service.run_retention_cleanup.return_value = mock_resp
        mock_service_cls.return_value = mock_service

        deleted = await run_scheduled_retention_cleanup()
        assert deleted == 42
        mock_service.run_retention_cleanup.assert_awaited_once_with(
            actor_id=None,
            permission="system.retention_cleanup",
        )


@pytest.mark.asyncio
async def test_run_scheduled_retention_cleanup_db_error_handled():
    with patch("src.modules.privacy.worker.SessionFactory") as mock_session_factory:
        mock_session_factory.side_effect = OperationalError(
            "connection refused", {}, None
        )

        deleted = await run_scheduled_retention_cleanup()
        assert deleted == 0


@pytest.mark.asyncio
async def test_retention_cleanup_loop_cancels_cleanly():
    task = asyncio.create_task(retention_cleanup_loop())
    await asyncio.sleep(0.01)
    task.cancel()
    # Awaiting task should finish without unhandled CancelledError exception
    await task
    assert task.cancelled() or task.done()
