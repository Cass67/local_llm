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
):
    """Search HuggingFace for GGUF models. Runs model-discovery.sh."""
    try:
        candidates = await asyncio.to_thread(cli.run_discovery, query, None, limit)
    except RuntimeError as e:
        return {"candidates": [], "error": str(e)}
    except Exception as e:
        return {"candidates": [], "error": f"Search failed: {e}"}
    return {"candidates": candidates, "error": None}


class InstallRequest(BaseModel):
    repo: str
    file: str
    profile: str = "balanced"


@router.post("/install")
async def install_model(req: InstallRequest):
    """Install a model candidate. Runs model-manager.sh install."""
    return await asyncio.to_thread(cli.run_install, req.repo, req.file, req.profile)
