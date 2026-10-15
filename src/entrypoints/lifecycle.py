import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from src.modules.billing.closure import closure_lifespan
from src.modules.ocpp.lifecycle import ocpp_lifespan
from src.modules.privacy.worker import retention_cleanup_loop
from src.modules.wallet.reconciliation import reconciliation_loop


@asynccontextmanager
async def application_lifespan(app: FastAPI) -> AsyncIterator[None]:
    async with ocpp_lifespan(app), closure_lifespan():
        recon_task = asyncio.create_task(reconciliation_loop())
        retention_task = asyncio.create_task(retention_cleanup_loop())
        try:
            yield
        finally:
            recon_task.cancel()
            retention_task.cancel()
            await asyncio.gather(recon_task, retention_task, return_exceptions=True)
