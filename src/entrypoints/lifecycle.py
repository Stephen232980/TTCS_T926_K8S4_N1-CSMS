import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from src.modules.ocpp.lifecycle import ocpp_lifespan
from src.modules.wallet.reconciliation import reconciliation_loop


@asynccontextmanager
async def application_lifespan(app: FastAPI) -> AsyncIterator[None]:
    async with ocpp_lifespan(app):
        task = asyncio.create_task(reconciliation_loop())
        try:
            yield
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
