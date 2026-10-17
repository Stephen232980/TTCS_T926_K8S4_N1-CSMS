"""Background retention cleanup loop for ephemeral and transient data."""

import asyncio
import logging

from sqlalchemy.exc import SQLAlchemyError

from src.config import settings
from src.modules.privacy.service import PrivacyRetentionService
from src.platform.database.session import SessionFactory

logger = logging.getLogger("csms.privacy")


async def run_scheduled_retention_cleanup() -> int:
    try:
        async with SessionFactory() as session:
            service = PrivacyRetentionService(session)
            result = await service.run_retention_cleanup(
                actor_id=None,
                permission="system.retention_cleanup",
            )
            logger.info(
                "privacy_retention_cleanup_blocked deleted_total=%d",
                result.total_deleted,
            )
            return result.total_deleted
    except SQLAlchemyError:
        logger.exception("privacy_retention_cleanup_failed")
        return 0


async def retention_cleanup_loop() -> None:
    while True:
        try:
            await asyncio.sleep(settings.retention_cleanup_interval_seconds)
            await run_scheduled_retention_cleanup()
        except asyncio.CancelledError:
            break
        except Exception:
            logger.exception("privacy_retention_cleanup_loop_unexpected_error")
