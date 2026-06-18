"""Search and install endpoints."""

import asyncio

from fastapi import APIRouter, Query
from pydantic import BaseModel
from .. import cli

router = APIRouter(prefix="/api/search", tags=["search"])


@router.get("")
async def search_models(
    query: str = Query(..., min_length=1, max_length=200),
    limit: int = Query(default=30, ge=1, le=100),
    vram_gb: float | None = Query(default=None, ge=1, le=512),
):
    """Search HuggingFace for GGUF models. Runs model-discovery.sh."""
    try:
        search_limit = 100 if vram_gb else limit
        candidates = await asyncio.to_thread(cli.run_discovery, query, None, search_limit)
    except RuntimeError as e:
        return {"candidates": [], "error": str(e)}
    except Exception as e:
        return {"candidates": [], "error": f"Search failed: {e}"}
    if vram_gb:
        candidates = [_with_target_vram(c, vram_gb) for c in candidates]
        candidates = [c for c in candidates if c.get("fit_level") != "too_tight"][:limit]
    return {"candidates": candidates, "error": None}


def _with_target_vram(candidate: dict, vram_gb: float) -> dict:
    required = candidate.get("memory_required_gb")
    notes = [n for n in candidate.get("notes", []) if "Asymmetric Split" not in str(n)]
    updated = {**candidate, "memory_available_gb": round(vram_gb, 2), "notes": notes}
    if not isinstance(required, int | float):
        return updated
    ratio = float(required) / vram_gb
    if ratio <= 0.70:
        fit = "perfect"
    elif ratio <= 0.85:
        fit = "good"
    elif ratio <= 0.95:
        fit = "marginal"
    else:
        fit = "too_tight"
    return {**updated, "fit_level": fit}


class InstallRequest(BaseModel):
    repo: str
    file: str
    profile: str = "balanced"


@router.post("/install")
async def install_model(req: InstallRequest):
    """Install a model candidate. Runs model-manager.sh install."""
    return await asyncio.to_thread(cli.run_install, req.repo, req.file, req.profile)
