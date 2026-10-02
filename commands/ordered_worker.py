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
from open_notebook.database.repository import ensure_record_id, repo_query

POLL_SECONDS = 1.0

# Embedding server unreachable (closed before Open Notebook, crashed): without
# this the worker drains the whole queue into 'failed' within seconds.
UNREACHABLE = ("All connection attempts failed", "Connection refused", "ConnectError")

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
        if "embed" in cmd["name"]:  # in finally: also when execute_command raises
            await pause_if_unreachable(cmd_id)


async def pause_if_unreachable(cmd_id) -> None:
    """Embed failed because the server is down: put it back and pause the queue."""
    rows = await repo_query("SELECT status, error_message FROM $id", {"id": cmd_id})
    row = rows[0] if rows else {}
    err = row.get("error_message") or ""
    if row.get("status") == "failed" and any(m in err for m in UNREACHABLE):
        await repo_query(
            "UPDATE $id SET status = 'new', error_message = NONE, started_at = NONE, finished_at = NONE",
            {"id": cmd_id},
        )
        await repo_query("UPSERT queue_state:main SET paused = true")
        logger.warning(f"Embedding server unreachable; requeued {cmd_id} and paused the queue")


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
