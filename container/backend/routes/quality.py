"""Golden-prompt quality checks — the half of a benchmark that speed cannot show."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .. import config, quality
from ..benchmark_store import BenchmarkStore
from ..clusters import get_cluster, read_active

router = APIRouter(prefix="/api/quality", tags=["quality"])


def _store() -> BenchmarkStore:
    return BenchmarkStore(config.RUNS_DIR / "benchmarks.sqlite3")


class QualityRunRequest(BaseModel):
    cluster_id: str = Field(min_length=1, max_length=100)
    max_tokens: int = Field(default=512, ge=16, le=8192)
    judge_url: str = Field(default="", max_length=500)
    judge_model: str = Field(default="", max_length=200)


class CasesUpdate(BaseModel):
    cases: list[dict[str, Any]]


@router.get("/cases")
async def get_cases():
    cases = quality.load_cases()
    return {"cases": cases, "is_default": cases is quality.DEFAULT_CASES}


@router.put("/cases")
async def put_cases(req: CasesUpdate):
    """Replace the golden set. An empty list restores the built-in defaults."""
    for case in req.cases:
        if not case.get("prompt"):
            raise HTTPException(status_code=422, detail="every case needs a prompt")
    path = config.STATE_DIR / "quality_set.json"
    if not req.cases:
        path.unlink(missing_ok=True)
        return {"status": "reset", "count": len(quality.DEFAULT_CASES)}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"cases": req.cases}, indent=2))
    return {"status": "saved", "count": len(req.cases)}


@router.post("/run")
async def run_quality_set(req: QualityRunRequest):
    """Run the golden set against whatever is loaded on a cluster."""
    cluster = get_cluster(req.cluster_id)
    if cluster is None:
        raise HTTPException(status_code=404, detail="cluster not found")
    active = read_active(req.cluster_id)
    if not active:
        raise HTTPException(status_code=409, detail="no model running on this cluster")
    model = str(active.get("model") or active.get("family") or "")
    report = await asyncio.to_thread(
        quality.run_quality,
        cluster.port,
        model,
        max_tokens=req.max_tokens,
        judge_url=req.judge_url,
        judge_model=req.judge_model,
    )
    profile = active.get("profile")
    _store().create_quality_run(
        model=model,
        profile=profile,
        cluster_id=req.cluster_id,
        passed=report["passed"],
        total=report["total"],
        pass_rate=report["pass_rate"],
        judge_mean=report["judge_mean"],
    )
    return {
        "cluster_id": req.cluster_id,
        "model": model,
        "profile": profile,
        **report,
    }
