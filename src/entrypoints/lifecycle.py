import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from src.modules.billing.closure import closure_lifespan
from src.modules.driver_notifications.worker import notification_loop
from src.modules.ocpp.lifecycle import ocpp_lifespan
from src.modules.privacy.worker import privacy_execution_loop, retention_cleanup_loop
from src.modules.wallet.reconciliation import reconciliation_loop


@asynccontextmanager
async def application_lifespan(app: FastAPI) -> AsyncIterator[None]:
    async with ocpp_lifespan(app), closure_lifespan():
        notification_task = asyncio.create_task(notification_loop())
        recon_task = asyncio.create_task(reconciliation_loop())
        retention_task = asyncio.create_task(retention_cleanup_loop())
        privacy_task = asyncio.create_task(privacy_execution_loop())
        try:
            yield
        finally:
            notification_task.cancel()
            recon_task.cancel()
            retention_task.cancel()
            privacy_task.cancel()
            await asyncio.gather(
                notification_task,
                recon_task,
                retention_task,
                privacy_task,
                return_exceptions=True,
            )
