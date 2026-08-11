"""Profile autotuner API — grid-search knobs, rank runs, promote the winner."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .. import sweep

router = APIRouter(prefix="/api/sweep", tags=["sweep"])


class SweepRequest(BaseModel):
    family: str = Field(min_length=1, max_length=200)
    cluster_id: str = Field(min_length=1, max_length=100)
    base_profile: str = Field(min_length=1, max_length=120)
    grid: dict[str, list[Any]]
    prompt_text: str = Field(min_length=1, max_length=20000)
    system_prompt: str = Field(default="", max_length=20000)
    max_tokens: int = Field(default=256, ge=16, le=8192)
    repeats: int = Field(default=2, ge=1, le=10)
    warmup: int = Field(default=1, ge=0, le=3)
    objective: str = Field(default="decode_tps")
    quality_gate: bool = False
    min_pass_rate: float = Field(default=1.0, ge=0, le=1)
    judge_url: str = Field(default="", max_length=500)
    judge_model: str = Field(default="", max_length=200)


class PromoteRequest(BaseModel):
    new_profile: str = Field(min_length=1, max_length=120)
    index: int | None = None  # defaults to the sweep's best result


_OBJECTIVES = {"decode_tps", "prompt_tps", "tps_per_watt"}


@router.get("/objectives")
async def objectives():
    return {"objectives": sorted(_OBJECTIVES)}


@router.post("")
async def start_sweep(req: SweepRequest):
    if req.objective not in _OBJECTIVES:
        raise HTTPException(status_code=422, detail=f"objective must be one of {_OBJECTIVES}")
    combos = sweep.expand_grid(req.grid)
    if not combos:
        raise HTTPException(status_code=422, detail="grid is empty")
    if len(combos) > sweep.MAX_COMBOS:
        raise HTTPException(
            status_code=422,
            detail=f"{len(combos)} combinations exceeds the {sweep.MAX_COMBOS} cap",
        )
    if sweep.base_profile_config(req.family, req.base_profile) is None:
        raise HTTPException(status_code=404, detail="base profile not found")
    job = sweep.create(**req.model_dump())
    return {"id": job.id, "total": len(combos), "status": job.status}


@router.get("")
async def list_sweeps():
    return {"sweeps": sweep.list_jobs()}


@router.get("/preview")
async def preview_grid(family: str, base_profile: str):
    """What the grid would cost before committing: each combo is a full model reload."""
    base = sweep.base_profile_config(family, base_profile)
    if base is None:
        raise HTTPException(status_code=404, detail="base profile not found")
    return {"base": base, "max_combos": sweep.MAX_COMBOS}


@router.get("/{job_id}")
async def get_sweep(job_id: str):
    job = sweep.get(job_id)
    if job is not None:
        return job.snapshot()
    persisted = sweep.load_persisted(job_id)
    if persisted is None:
        raise HTTPException(status_code=404, detail="sweep not found")
    return persisted


@router.post("/{job_id}/cancel")
async def cancel_sweep(job_id: str):
    job = sweep.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="sweep not found")
    job.cancel()
    return {"cancelled": True, "status": job.status}


@router.post("/{job_id}/promote")
async def promote_result(job_id: str, req: PromoteRequest):
    """Save a sweep result's config as a real named profile."""
    snapshot = sweep.get(job_id).snapshot() if sweep.get(job_id) else sweep.load_persisted(job_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="sweep not found")

    if req.index is None:
        winner = snapshot.get("best")
        if winner is None:
            raise HTTPException(status_code=409, detail="sweep has no successful result yet")
    else:
        matches = [r for r in snapshot["results"] if r["index"] == req.index]
        if not matches:
            raise HTTPException(status_code=404, detail="result index not found")
        winner = matches[0]

    base = sweep.base_profile_config(snapshot["family"], snapshot["base_profile"])
    if base is None:
        raise HTTPException(status_code=404, detail="base profile no longer exists")

    name = req.new_profile.strip().lower()
    if name.endswith("-sweep"):
        raise HTTPException(status_code=422, detail="'-sweep' is reserved for scratch profiles")
    config = {**base, **winner["combo"]}
    sweep.write_scratch_profile(snapshot["family"], name, config)
    return {"status": "saved", "profile": name, "config": config, "from_index": winner["index"]}
