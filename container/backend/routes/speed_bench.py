"""SPEED-Bench sweeps: one job at a time, against one running cluster."""

import os
import threading
import time
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import speed_bench
from ..clusters import get_cluster, list_active

router = APIRouter(prefix="/api/speed-bench", tags=["speed-bench"])

# Point this at NVIDIA prepare.py output to run the 494 rows that ship unhydrated.
PROMPTS_JSONL = os.environ.get("SPEED_BENCH_PROMPTS_JSONL", "")

_job: dict[str, Any] = {"running": False}
_job_lock = threading.Lock()


class RunRequest(BaseModel):
    cluster_id: str
    categories: list[str] = []
    per_category: int = 10
    max_tokens: int = 256
    timeout: float = 900.0


@router.get("/categories")
async def list_categories():
    """Which domains can be run, and what never hydrated."""
    try:
        return speed_bench.categories(PROMPTS_JSONL)
    except (httpx.HTTPError, OSError, KeyError) as exc:
        raise HTTPException(502, f"could not load SPEED-Bench prompts: {exc}") from exc


@router.get("/status")
async def status():
    """Live progress plus the rows measured so far; the last report when idle."""
    return {
        "running": _job.get("running", False),
        "cluster_name": _job.get("cluster_name"),
        "model": _job.get("model"),
        "total": _job.get("total", 0),
        "done": _job.get("done", 0),
        "current": _job.get("current"),
        "started": _job.get("started"),
        "errors": _job.get("errors", []),
        "rows": _job.get("rows", []),
        "report": speed_bench.last_report(),
    }


@router.post("/stop")
async def stop():
    """Finish after the row in flight; partial results are still reported."""
    if not _job.get("running"):
        raise HTTPException(409, "no sweep is running")
    _job["cancel"] = True
    return {"status": "stopping"}


def _run(cluster, model: str, rows: list[dict], req: RunRequest) -> None:
    try:
        speed_bench.run_sweep(cluster, model, rows, req.max_tokens, req.timeout, _job)
    finally:
        _job.update(running=False, current=None)


@router.post("/run")
async def run(req: RunRequest):
    """Sweep the selected categories against a running cluster."""
    cluster = get_cluster(req.cluster_id)
    if cluster is None:
        raise HTTPException(404, f"unknown cluster '{req.cluster_id}'")
    active = next((a for a in list_active() if a.get("cluster_id") == req.cluster_id), None)
    if not active:
        raise HTTPException(409, f"cluster '{cluster.name}' has no model loaded")
    model = str(active.get("model") or active.get("family") or "")

    try:
        prompts, _ = speed_bench.load_prompts(PROMPTS_JSONL)
    except (httpx.HTTPError, OSError, KeyError) as exc:
        raise HTTPException(502, f"could not load SPEED-Bench prompts: {exc}") from exc
    rows = speed_bench.select_rows(prompts, req.categories, req.per_category)
    if not rows:
        raise HTTPException(400, "no prompts match that selection")

    with _job_lock:
        if _job.get("running"):
            raise HTTPException(409, "a sweep is already running")
        _job.clear()
        _job.update(
            running=True,
            cancel=False,
            cluster_name=cluster.name,
            model=model,
            total=len(rows),
            done=0,
            current=None,
            started=time.time(),
            errors=[],
            rows=[],
        )
    threading.Thread(target=_run, args=(cluster, model, rows, req), daemon=True).start()
    return {"status": "started", "total": len(rows), "model": model}
