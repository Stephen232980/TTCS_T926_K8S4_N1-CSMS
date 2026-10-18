"""Retry monthly subscription wallet debits without blocking API requests."""

import asyncio
import logging
from datetime import UTC, datetime

from src.modules.subscriptions.service import gia_han_den_han
from src.platform.database.session import SessionFactory

logger = logging.getLogger("csms.subscriptions")


async def subscription_renewal_loop() -> None:
    while True:
        try:
            async with SessionFactory() as db, db.begin():
                renewed = await gia_han_den_han(db, now=datetime.now(UTC))
            if renewed:
                logger.info("monthly_subscriptions_renewed count=%s", renewed)
        except Exception:
            logger.exception("monthly_subscription_renewal_failed")
        await asyncio.sleep(60)
