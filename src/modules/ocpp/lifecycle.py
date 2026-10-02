"""Periodic retention cleanup for persistent OCPP replies."""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy.exc import SQLAlchemyError

from src.config import settings
from src.modules.ocpp.dispatcher import prune_replies
from src.platform.database.session import SessionFactory


async def cleanup_loop() -> None:
    while True:
        await asyncio.sleep(settings.ocpp_reply_cleanup_interval_seconds)
        try:
            async with SessionFactory() as session, session.begin():
                await prune_replies(session)
        except SQLAlchemyError:
            logging.getLogger("csms.ocpp").error("ocpp_reply_cleanup_failed")


@asynccontextmanager
async def ocpp_lifespan(app: FastAPI) -> AsyncIterator[None]:
    task = asyncio.create_task(cleanup_loop())
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
