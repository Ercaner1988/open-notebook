"""Ordered, pausable single-command worker (replaces `surreal-commands-worker`).

Run: python -m commands.ordered_worker
Picks one status='new' command at a time by (queue_priority ASC, queued_at ASC),
skipping work while `queue_state:main.paused` is true. A running command always
finishes; pausing only stops picking new ones.

surreal-commands stores no timestamps on `command` records, so this worker
stamps its own: `queued_at` (first poll that sees the command - within
POLL_SECONDS of submission), `started_at` and `finished_at`. The queue API
reads them for ordering, rate and ETA.
"""

import asyncio

from loguru import logger

import commands  # noqa: F401  registers all commands (like --import-modules commands)
from open_notebook.database.repository import (
    db_connection,
    ensure_record_id,
    parse_record_ids,
)

POLL_SECONDS = 1.0

# One long-lived connection instead of the stock repo_query's connect + sign-in
# per call: sign-in costs ~1 s (argon2), and this loop queries every second.
_conn = None  # (context manager, db)


async def repo_query(query, vars=None):
    global _conn
    if _conn is None:
        cm = db_connection()
        _conn = (cm, await cm.__aenter__())
    try:
        result = parse_record_ids(await _conn[1].query(query, vars))
    except Exception:
        cm, _conn = _conn[0], None  # reconnect on next call
        try:
            await cm.__aexit__(None, None, None)
        except Exception:
            pass  # the connection is already broken; nothing left to close
        raise
    if isinstance(result, str):
        raise RuntimeError(result)
    return result

STAMP_QUERY = "UPDATE command SET queued_at = time::now() WHERE status = 'new' AND queued_at = NONE"
# SurrealDB 2.x ORDER BY takes field names, not expressions: alias first.
PICK_QUERY = (
    "SELECT *, queue_priority ?? 0 AS qp FROM command WHERE status = 'new' "
    "ORDER BY qp ASC, queued_at ASC LIMIT 1"
)


async def is_paused() -> bool:
    rows = await repo_query("SELECT paused FROM queue_state:main")
    return bool(rows and rows[0].get("paused"))


async def pick_next():
    """Next command to run, or None when paused / queue empty."""
    if await is_paused():
        return None
    await repo_query(STAMP_QUERY)
    rows = await repo_query(PICK_QUERY)
    return rows[0] if rows else None


async def run_one(cmd: dict) -> None:
    from surreal_commands.core.service import command_service

    cmd_id = ensure_record_id(cmd["id"])
    logger.info(f"Running {cmd['app']}.{cmd['name']} {cmd['id']}")
    await repo_query("UPDATE $id SET started_at = time::now()", {"id": cmd_id})
    try:
        await command_service.execute_command(
            cmd_id,
            f"{cmd['app']}.{cmd['name']}",
            cmd.get("args") or {},
            cmd.get("context"),
        )
    finally:
        await repo_query("UPDATE $id SET finished_at = time::now()", {"id": cmd_id})


async def main() -> None:
    logger.info("Ordered worker started")
    while True:
        try:
            cmd = await pick_next()
            if cmd is None:
                await asyncio.sleep(POLL_SECONDS)
                continue
            await run_one(cmd)
        except Exception as e:  # keep the loop alive across DB hiccups
            logger.error(f"Ordered worker error: {e}")
            await asyncio.sleep(POLL_SECONDS)


if __name__ == "__main__":
    asyncio.run(main())
