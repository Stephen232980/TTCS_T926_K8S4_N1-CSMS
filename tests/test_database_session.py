from collections.abc import AsyncIterator
from typing import Self

import pytest

from src.platform.database import session as session_module


class FakeSession:
    def __init__(self) -> None:
        self.commit_count = 0
        self.rollback_count = 0

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: object,
    ) -> None:
        return None

    async def commit(self) -> None:
        self.commit_count += 1

    async def rollback(self) -> None:
        self.rollback_count += 1


@pytest.mark.asyncio
async def test_db_session_commits_after_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_session = FakeSession()
    monkeypatch.setattr(session_module, "SessionFactory", lambda: fake_session)

    dependency: AsyncIterator[object] = session_module.get_db_session()
    assert await anext(dependency) is fake_session

    with pytest.raises(StopAsyncIteration):
        await anext(dependency)

    assert fake_session.commit_count == 1
    assert fake_session.rollback_count == 0


@pytest.mark.asyncio
async def test_db_session_rolls_back_after_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_session = FakeSession()
    monkeypatch.setattr(session_module, "SessionFactory", lambda: fake_session)

    dependency: AsyncIterator[object] = session_module.get_db_session()
    assert await anext(dependency) is fake_session

    with pytest.raises(RuntimeError, match="request failed"):
        await dependency.athrow(RuntimeError("request failed"))

    assert fake_session.commit_count == 0
    assert fake_session.rollback_count == 1
