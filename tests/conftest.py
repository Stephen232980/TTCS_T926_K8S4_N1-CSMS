import asyncio
import os
import sys
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

if "DATABASE_URL" not in os.environ:
    env_file = Path(__file__).resolve().parent.parent / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

# Only disposable test databases use this fixed explicit migration cutoff.
os.environ.setdefault("LEGACY_SETTLEMENT_CUTOFF", "1970-01-01T00:00:00+00:00")

from src.platform.database.session import SessionFactory

if sys.platform == "win32":

    @pytest.fixture(scope="session")
    def event_loop_policy() -> asyncio.AbstractEventLoopPolicy:
        return asyncio.WindowsSelectorEventLoopPolicy()


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    async with SessionFactory() as session:
        yield session
        await session.rollback()
