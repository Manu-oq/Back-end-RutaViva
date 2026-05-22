from __future__ import annotations

import pytest

from app.repositories.base import BaseRepository


class FakeAsyncSession:
    def __init__(self, *, fail_commit: bool = False) -> None:
        self.fail_commit = fail_commit
        self.commits = 0
        self.rollbacks = 0

    async def commit(self) -> None:
        self.commits += 1
        if self.fail_commit:
            raise RuntimeError("commit failed")

    async def rollback(self) -> None:
        self.rollbacks += 1


@pytest.mark.asyncio
async def test_commit_or_rollback_commits_once_on_success() -> None:
    session = FakeAsyncSession()

    await BaseRepository()._commit_or_rollback(session)  # type: ignore[arg-type]

    assert session.commits == 1
    assert session.rollbacks == 0


@pytest.mark.asyncio
async def test_commit_or_rollback_rolls_back_on_commit_error() -> None:
    session = FakeAsyncSession(fail_commit=True)

    with pytest.raises(RuntimeError, match="commit failed"):
        await BaseRepository()._commit_or_rollback(session)  # type: ignore[arg-type]

    assert session.commits == 1
    assert session.rollbacks == 1
