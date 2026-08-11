"""Bake-off jobs — run the same measurements across several models back to back."""

from __future__ import annotations

import asyncio
import time
import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .. import bakeoff
from ..clusters import get_cluster

router = APIRouter(prefix="/api/bakeoff", tags=["bakeoff"])

_JOBS: dict[str, bakeoff.BakeoffJob] = {}


class EntryRequest(BaseModel):
    family: str = Field(min_length=1, max_length=200)
    profile: str = Field(default="", max_length=100)


class BakeoffRequest(BaseModel):
    cluster_id: str = Field(min_length=1, max_length=100)
    entries: list[EntryRequest] = Field(min_length=1, max_length=20)
    prompt_text: str = Field(default=bakeoff.DEFAULT_PROMPT, min_length=1, max_length=20000)
    max_tokens: int = Field(default=256, ge=16, le=8192)
    repeats: int = Field(default=3, ge=1, le=10)
    quality: bool = True


@router.post("/start")
async def start_bakeoff(req: BakeoffRequest):
    cluster = get_cluster(req.cluster_id)
    if cluster is None:
        raise HTTPException(status_code=404, detail="cluster not found")
    if any(job.status == "running" for job in _JOBS.values()):
        raise HTTPException(status_code=409, detail="a bake-off is already running")

    job_id = f"bakeoff-{int(time.time())}-{uuid.uuid4().hex[:6]}"
    job = bakeoff.BakeoffJob(id=job_id, cluster_id=req.cluster_id, total=len(req.entries))
    _JOBS[job_id] = job
    entries = [bakeoff.BakeoffEntry(family=e.family, profile=e.profile) for e in req.entries]
    job.say(f"queued {len(entries)} entries on {cluster.name}")

    async def _execute() -> None:
        try:
            await asyncio.to_thread(
                bakeoff.run_bakeoff,
                job,
                cluster,
                entries,
                prompt=req.prompt_text,
                max_tokens=req.max_tokens,
                repeats=req.repeats,
                with_quality=req.quality,
            )
        except Exception as exc:  # noqa: BLE001
            job.status = "error"
            job.error = str(exc)
            job.say(f"aborted: {exc}")

    asyncio.create_task(_execute())  # noqa: RUF006
    return {"job_id": job_id}


@router.get("/jobs")
async def list_jobs():
    """Newest first, so a reloaded tab can reattach to a run in progress."""
    jobs = sorted(_JOBS.values(), key=lambda j: j.started_at, reverse=True)
    return {"jobs": [job.snapshot() for job in jobs[:10]]}


@router.get("/jobs/{job_id}")
async def get_job(job_id: str):
    job = _JOBS.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return job.snapshot()


@router.post("/jobs/{job_id}/cancel")
async def cancel_job(job_id: str):
    """Ask the job to stop. It finishes the request in flight first — killing a
    load mid-flight would leave a half-created runner container behind."""
    job = _JOBS.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    job.cancelled = True
    job.say("cancel requested — stopping after the current step")
    return {"status": "cancelling"}
