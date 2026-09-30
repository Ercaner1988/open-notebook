from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from api.routers import embedding_queue as eq
from api.routers.embedding_queue import MoveRequest
from commands import ordered_worker as ow


def _fake_db(cmds, paused=False):
    """repo_query stand-in that applies the worker's ordering to an in-memory list."""

    async def fake(query, vars=None):
        if "queue_state" in query:
            return [{"paused": paused}]
        new = [c for c in cmds if c["status"] == "new"]
        new.sort(key=lambda c: (c.get("queue_priority") or 0, c["queued_at"]))
        return new[:1]

    return fake


CMDS = [
    {"id": "command:a", "status": "new", "queued_at": 1},
    {"id": "command:b", "status": "new", "queued_at": 2, "queue_priority": -1},
    {"id": "command:c", "status": "new", "queued_at": 0, "queue_priority": 5},
    {"id": "command:d", "status": "completed", "queued_at": -9},
]


@pytest.mark.asyncio
async def test_pick_order_priority_then_queued_at():
    with patch.object(ow, "repo_query", _fake_db(CMDS)):
        assert (await ow.pick_next())["id"] == "command:b"
        same = [
            {"id": "command:x", "status": "new", "queued_at": 2},
            {"id": "command:y", "status": "new", "queued_at": 1},
        ]
    with patch.object(ow, "repo_query", _fake_db(same)):
        assert (await ow.pick_next())["id"] == "command:y"


@pytest.mark.asyncio
async def test_pick_paused_returns_none():
    with patch.object(ow, "repo_query", _fake_db(CMDS, paused=True)):
        assert await ow.pick_next() is None


@pytest.mark.asyncio
@pytest.mark.parametrize("pos,expected", [("top", -3), ("bottom", 8)])
async def test_move_top_bottom(pos, expected):
    calls = []

    async def fake(query, vars=None):
        calls.append((query, vars))
        if query.startswith("SELECT * FROM command WHERE id"):
            return [{"id": "command:a", "status": "new"}]
        if query.startswith("SELECT VALUE"):
            return [0, -2, 7]
        return []

    with patch.object(eq, "repo_query", fake):
        res = await eq.move_job("command:a", MoveRequest(position=pos))
    assert res["queue_priority"] == expected
    assert calls[-1][1]["p"] == expected


@pytest.mark.asyncio
async def test_move_non_new_is_400():
    with patch.object(
        eq, "repo_query", AsyncMock(return_value=[{"id": "command:a", "status": "running"}])
    ):
        with pytest.raises(HTTPException) as e:
            await eq.move_job("command:a", MoveRequest(position="top"))
    assert e.value.status_code == 400


@pytest.mark.asyncio
async def test_retry_failed_dedupes_and_skips_pending():
    async def fake(query, vars=None):
        if "status = 'failed'" in query:  # s1 twice, s2 (no text), s3 (pending), s4 (has embeddings)
            return ["source:s1", "source:s1", "source:s2", "source:s3", "source:s4"]
        if "status IN" in query:
            return ["source:s3"]
        if query.startswith("RETURN"):  # sources that already have embeddings
            return ["source:s4"]
        # unembedded: s1, s3 have text; s2 empty; s4 is embedded so absent
        return [
            {"id": "source:s1", "title": "1", "has_text": True},
            {"id": "source:s2", "title": "2", "has_text": False},
            {"id": "source:s3", "title": "3", "has_text": True},
            {"id": "source:s9", "title": "9", "has_text": True},  # never failed
        ]

    submit = AsyncMock(return_value="command:new")
    with patch.object(eq, "repo_query", fake), patch.object(eq, "_submit_embed", submit):
        res = await eq.retry_failed()
    assert res == {"queued": 1}
    submit.assert_awaited_once_with("source:s1")


@pytest.mark.asyncio
async def test_test_embedding_dangling_default():
    defaults = type("D", (), {"default_embedding_model": "model:gone"})()
    with (
        patch.object(eq.DefaultModels, "get_instance", AsyncMock(return_value=defaults)),
        patch.object(eq.Model, "get", AsyncMock(side_effect=Exception("not found"))),
    ):
        res = await eq.test_embedding()
    assert res["ok"] is False and res["model_id"] is None
    assert "model:gone" in res["message"]


@pytest.mark.asyncio
async def test_test_embedding_ok():
    defaults = type("D", (), {"default_embedding_model": "model:m"})()
    with (
        patch.object(eq.DefaultModels, "get_instance", AsyncMock(return_value=defaults)),
        patch.object(eq.Model, "get", AsyncMock(return_value=object())),
        patch.object(eq, "test_individual_model", AsyncMock(return_value=(True, "fine"))),
    ):
        assert await eq.test_embedding() == {"ok": True, "message": "fine", "model_id": "model:m"}
