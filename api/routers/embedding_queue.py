"""Embedding queue: inspect / pause / reorder embed_source jobs plus maintenance.

The worker that honours pause and queue_priority is `commands/ordered_worker.py`.
"""

from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, HTTPException, Query
from loguru import logger
from pydantic import BaseModel

from api.command_service import CommandService
from open_notebook.ai.connection_tester import test_individual_model
from open_notebook.ai.models import DefaultModels, Model
from open_notebook.database.repository import (
    db_connection,
    ensure_record_id,
    parse_record_ids,
    repo_query,
)

router = APIRouter(prefix="/embedding-queue")

EMBED = "name = 'embed_source'"
PENDING = f"{EMBED} AND status IN ['new', 'running']"


class MoveRequest(BaseModel):
    position: Literal["top", "bottom"]


# ---------------------------------------------------------------- helpers


async def _run(db, query: str, vars: Optional[Dict[str, Any]] = None) -> Any:
    """repo_query on an already-open connection.

    repo_query opens a new connection and signs in for every call, and the
    sign-in (argon2 password check) costs ~1 s on this setup - so /summary,
    polled every 5 s with 7 queries, took 5-30 s. Endpoints that run several
    queries share one connection through this instead.
    """
    result = parse_record_ids(await db.query(query, vars))
    if isinstance(result, str):
        raise RuntimeError(result)
    return result


async def _titles(source_ids: List[str], q=repo_query) -> Dict[str, str]:
    ids = list({s for s in source_ids if s})
    if not ids:
        return {}
    rows = await q(
        "SELECT id, title FROM source WHERE id IN $ids",
        {"ids": [ensure_record_id(i) for i in ids]},
    )
    return {str(r["id"]): r.get("title") or "" for r in rows}


async def _set_paused(paused: bool) -> Dict[str, bool]:
    await repo_query("UPSERT queue_state:main SET paused = $p", {"p": paused})
    return {"paused": paused}


async def _pending_source_ids() -> set:
    rows = await repo_query(f"SELECT VALUE args.source_id FROM command WHERE {PENDING}")
    return {str(r) for r in rows if r}


async def _unembedded() -> Dict[str, List[Dict[str, Any]]]:
    """Sources with zero source_embedding rows, split by non-empty full_text."""
    # Two calls, not `LET $done ...; SELECT ...`: repo_query returns the first
    # statement's result (the LET's None). Computed once so the NOTINSIDE
    # doesn't rescan ~80k source_embedding rows per source.
    done = await repo_query(
        "RETURN array::distinct((SELECT VALUE source FROM source_embedding))"
    )
    rows = await repo_query(
        "SELECT id, title, string::len(string::trim(full_text ?? '')) > 0 AS has_text "
        "FROM source WHERE id NOTINSIDE $done",
        # repo_query hands record ids back as strings; NOTINSIDE needs RecordIDs.
        {"done": [ensure_record_id(d) for d in (done or [])]},
    )
    out: Dict[str, List[Dict[str, Any]]] = {"with_text": [], "empty_text": []}
    for r in rows:
        item = {"source_id": str(r["id"]), "title": r.get("title") or ""}
        out["with_text" if r.get("has_text") else "empty_text"].append(item)
    return out


async def _submit_embed(source_id: str) -> str:
    import commands.embedding_commands  # noqa: F401  (register before submit)

    return await CommandService.submit_command_job(
        "open_notebook", "embed_source", {"source_id": source_id}
    )


async def _submit_many(source_ids: List[str]) -> int:
    for sid in source_ids:
        await _submit_embed(sid)
    return len(source_ids)


async def retry_failed_candidates() -> List[str]:
    """Failed sources that still lack embeddings, have text, and aren't pending."""
    failed = await repo_query(
        f"SELECT VALUE args.source_id FROM command WHERE {EMBED} AND status = 'failed'"
    )
    failed_ids = {str(f) for f in failed if f}
    pending = await _pending_source_ids()
    with_text = [s["source_id"] for s in (await _unembedded())["with_text"]]
    return [s for s in with_text if s in failed_ids and s not in pending]


# ---------------------------------------------------------------- queue


@router.get("/summary")
async def summary():
    try:
        async with db_connection() as db:
            return await _summary(lambda query, vars=None: _run(db, query, vars))
    except Exception as e:
        logger.error(f"Error building embedding queue summary: {e}")
        raise HTTPException(status_code=500, detail=str(e))


async def _summary(q) -> Dict[str, Any]:
    rows = await q(
        f"SELECT status, count() AS n FROM command WHERE {EMBED} GROUP BY status"
    )
    counts = {k: 0 for k in ("new", "running", "completed", "failed", "canceled")}
    for r in rows:
        if r["status"] in counts:
            counts[r["status"]] = r["n"]

    running = await q(
        f"SELECT id, args, started_at FROM command WHERE {EMBED} AND status = 'running'"
    )
    titles = await _titles([(r.get("args") or {}).get("source_id") for r in running], q)
    chunks = await q("SELECT count() AS n FROM source_embedding GROUP ALL")
    state = await q("SELECT paused FROM queue_state:main")

    # source_embedding has no timestamp, so throughput comes from completed jobs'
    # results (chunks_created / processing_time). finished_at is stamped by
    # commands/ordered_worker.py; jobs run by the stock worker have none.
    # A 1 h window, not 10 min: a single book can take 25+ minutes, and a
    # shorter window often held no finished job, so the rate showed "—".
    recent = await q(
        f"SELECT math::sum(result.chunks_created ?? 0) AS chunks FROM command "
        f"WHERE {EMBED} AND status = 'completed' "
        "AND finished_at > time::now() - 1h GROUP ALL"
    )
    chunks_1h = (recent[0].get("chunks") or 0) if recent else 0
    rate = round(chunks_1h / 60, 1) if chunks_1h else None

    # ponytail: ETA = queued jobs x mean processing_time of jobs completed in the
    # last hour (single worker). Ignores per-source size differences.
    avg = await q(
        f"SELECT math::mean(result.processing_time) AS s FROM command "
        f"WHERE {EMBED} AND status = 'completed' "
        "AND finished_at > time::now() - 1h GROUP ALL"
    )
    avg_s = avg[0].get("s") if avg else None
    eta = round(counts["new"] * avg_s / 60, 1) if avg_s else None

    return {
        "paused": bool(state and state[0].get("paused")),
        "counts": counts,
        "running": [
            {
                "id": str(r["id"]),
                "source_id": (r.get("args") or {}).get("source_id"),
                "source_title": titles.get((r.get("args") or {}).get("source_id")),
                "started": str(r["started_at"]) if r.get("started_at") else None,
            }
            for r in running
        ],
        "embedded_chunks": chunks[0]["n"] if chunks else 0,
        "rate_chunks_per_min": rate,
        "eta_minutes": eta,
    }


@router.get("/jobs")
async def list_jobs(
    status: Optional[Literal["new", "running", "failed", "completed"]] = None,
    limit: int = Query(100, ge=1, le=1000),
):
    try:
        where = f"{EMBED}" + (" AND status = $status" if status else "")
        # ORDER BY takes field names, not expressions (SurrealDB 2.x): alias qp.
        order = "qp ASC, queued_at ASC" if status == "new" else "finished_at DESC"
        async with db_connection() as db:
            rows = await _run(
                db,
                f"SELECT *, queue_priority ?? 0 AS qp FROM command WHERE {where} "
                f"ORDER BY {order} LIMIT $limit",
                {"status": status, "limit": limit},
            )
            titles = await _titles(
                [(r.get("args") or {}).get("source_id") for r in rows],
                lambda query, vars=None: _run(db, query, vars),
            )
        return [
            {
                "id": str(r["id"]),
                "status": r.get("status"),
                "source_id": (r.get("args") or {}).get("source_id"),
                "source_title": titles.get((r.get("args") or {}).get("source_id")),
                "created": str(r["queued_at"]) if r.get("queued_at") else None,
                "updated": str(r["finished_at"]) if r.get("finished_at") else None,
                "queue_priority": r.get("queue_priority") or 0,
                "error_message": r.get("error_message") or None,
            }
            for r in rows
        ]
    except Exception as e:
        logger.error(f"Error listing embedding jobs: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/pause")
async def pause():
    return await _set_paused(True)


@router.post("/resume")
async def resume():
    return await _set_paused(False)


async def _get_job(job_id: str) -> Dict[str, Any]:
    rows = await repo_query(
        f"SELECT * FROM command WHERE id = $id AND {EMBED}",
        {"id": ensure_record_id(job_id)},
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Job not found")
    return rows[0]


@router.post("/jobs/{job_id}/move")
async def move_job(job_id: str, body: MoveRequest):
    job = await _get_job(job_id)
    if job.get("status") != "new":
        raise HTTPException(status_code=400, detail="Only 'new' jobs can be moved")
    prios = await repo_query(
        f"SELECT VALUE (queue_priority ?? 0) FROM command WHERE {EMBED} AND status = 'new'"
    )
    prio = (min(prios) - 1) if body.position == "top" else (max(prios) + 1)
    await repo_query(
        "UPDATE $id SET queue_priority = $p", {"id": ensure_record_id(job_id), "p": prio}
    )
    return {"job_id": job_id, "queue_priority": prio}


@router.post("/jobs/{job_id}/cancel")
async def cancel_job(job_id: str):
    job = await _get_job(job_id)
    if job.get("status") != "new":
        raise HTTPException(
            status_code=400, detail="Only 'new' jobs can be canceled (a running job cannot be stopped)"
        )
    # CommandService.cancel_command_job is only a logging stub, so mark it canceled here;
    # the ordered worker only picks status='new'.
    ok = await CommandService.cancel_command_job(job_id)
    await repo_query(
        "UPDATE $id SET status = 'canceled'", {"id": ensure_record_id(job_id)}
    )
    return {"job_id": job_id, "cancelled": ok}


@router.post("/jobs/{job_id}/retry")
async def retry_job(job_id: str):
    job = await _get_job(job_id)
    source_id = (job.get("args") or {}).get("source_id")
    if not source_id:
        raise HTTPException(status_code=400, detail="Job has no source_id")
    try:
        return {"command_id": await _submit_embed(source_id)}
    except Exception as e:
        logger.error(f"Failed to resubmit embed job: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/retry-failed")
async def retry_failed():
    try:
        return {"queued": await _submit_many(await retry_failed_candidates())}
    except Exception as e:
        logger.error(f"retry-failed error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------- maintenance


@router.get("/maintenance/unembedded")
async def unembedded():
    try:
        return await _unembedded()
    except Exception as e:
        logger.error(f"unembedded error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/maintenance/enqueue-unembedded")
async def enqueue_unembedded():
    try:
        pending = await _pending_source_ids()
        todo = [
            s["source_id"]
            for s in (await _unembedded())["with_text"]
            if s["source_id"] not in pending
        ]
        return {"queued": await _submit_many(todo)}
    except Exception as e:
        logger.error(f"enqueue-unembedded error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/maintenance/unused-credentials")
async def unused_credentials():
    try:
        rows = await repo_query(
            "SELECT id, name, provider, base_url FROM credential WHERE id NOTINSIDE "
            "array::distinct((SELECT VALUE credential FROM model WHERE credential != NONE))"
        )
        return [
            {
                "id": str(r["id"]),
                "name": r.get("name"),
                "provider": r.get("provider"),
                "base_url": r.get("base_url"),
            }
            for r in rows
        ]
    except Exception as e:
        logger.error(f"unused-credentials error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/maintenance/test-embedding")
async def test_embedding():
    defaults = await DefaultModels.get_instance()
    model_id = getattr(defaults, "default_embedding_model", None)
    if not model_id:
        return {"ok": False, "message": "No default embedding model is set.", "model_id": None}
    try:
        model = await Model.get(model_id)
    except Exception:
        model = None
    if not model:
        return {
            "ok": False,
            "message": f"Default embedding model '{model_id}' does not exist "
            "(dangling default). Pick a new default in Models.",
            "model_id": None,
        }
    try:
        ok, message = await test_individual_model(model)
    except Exception as e:
        return {"ok": False, "message": str(e)[:200], "model_id": str(model_id)}
    return {"ok": ok, "message": message, "model_id": str(model_id)}
