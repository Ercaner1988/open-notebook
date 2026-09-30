"""db_connection() reuses signed-in connections and never reuses a failed one."""

from unittest.mock import AsyncMock, patch

import pytest

from open_notebook.database import repository


def _fake_surreal():
    opened = []

    def factory(url):
        db = AsyncMock()
        opened.append(db)
        return db

    return factory, opened


@pytest.mark.asyncio
async def test_reuses_connection_and_signs_in_once():
    factory, opened = _fake_surreal()
    with patch.object(repository, "AsyncSurreal", side_effect=factory):
        async with repository.db_connection() as first:
            pass
        async with repository.db_connection() as second:
            pass
    assert first is second
    assert len(opened) == 1
    opened[0].signin.assert_awaited_once()
    opened[0].close.assert_not_awaited()


@pytest.mark.asyncio
async def test_failed_block_closes_connection_instead_of_pooling():
    factory, opened = _fake_surreal()
    with patch.object(repository, "AsyncSurreal", side_effect=factory):
        with pytest.raises(RuntimeError):
            async with repository.db_connection():
                raise RuntimeError("socket broke")
        async with repository.db_connection():
            pass
    assert len(opened) == 2
    opened[0].close.assert_awaited_once()


@pytest.mark.asyncio
async def test_concurrent_borrowers_get_distinct_connections():
    factory, opened = _fake_surreal()
    with patch.object(repository, "AsyncSurreal", side_effect=factory):
        async with repository.db_connection() as a:
            async with repository.db_connection() as b:
                assert a is not b
    assert len(opened) == 2


@pytest.mark.asyncio
async def test_stale_idle_connection_is_replaced():
    factory, opened = _fake_surreal()
    with patch.object(repository, "AsyncSurreal", side_effect=factory):
        async with repository.db_connection():
            pass
        with patch.object(repository, "_POOL_MAX_IDLE_SECONDS", -1):
            async with repository.db_connection():
                pass
    assert len(opened) == 2
    opened[0].close.assert_awaited_once()
