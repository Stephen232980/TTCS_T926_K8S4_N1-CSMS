"""Periodic retention cleanup for persistent OCPP replies."""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy.exc import SQLAlchemyError

from src.config import settings
from src.modules.charging.recovery import flag_abnormal_sessions
from src.modules.ocpp.control import control_loop
from src.modules.ocpp.dispatcher import prune_replies
from src.modules.ocpp.monitoring import expire_chargers
from src.platform.database.session import SessionFactory


async def cleanup_loop() -> None:
    while True:
        await asyncio.sleep(settings.ocpp_reply_cleanup_interval_seconds)
        try:
            async with SessionFactory() as session, session.begin():
                await prune_replies(session)
        except SQLAlchemyError:
            logging.getLogger("csms.ocpp").error("ocpp_reply_cleanup_failed")


async def offline_loop() -> None:
    while True:
        try:
            async with SessionFactory() as session, session.begin():
                await expire_chargers(session)
        except SQLAlchemyError:
            logging.getLogger("csms.ocpp").error("ocpp_offline_scan_failed")
        await asyncio.sleep(1)


@asynccontextmanager
async def ocpp_lifespan(app: FastAPI) -> AsyncIterator[None]:
    tasks = [
        asyncio.create_task(cleanup_loop()),
        asyncio.create_task(offline_loop()),
        asyncio.create_task(recovery_loop()),
        asyncio.create_task(control_loop()),
    ]
    try:
        yield
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def recovery_loop() -> None:
    while True:
        try:
            async with SessionFactory() as session, session.begin():
                await flag_abnormal_sessions(session)
        except SQLAlchemyError:
            logging.getLogger("csms.ocpp").error("charging_recovery_scan_failed")
        await asyncio.sleep(settings.charging_recovery_scan_interval_seconds)
