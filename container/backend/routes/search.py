"""Search and install endpoints."""
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
        candidates = cli.run_discovery(query, host=None, limit=limit)
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
    import json
    import subprocess

    cmd = [
        "bash",
        str(cli.MODEL_MANAGER),
        "install",
        "--repo",
        req.repo,
        "--file",
        req.file,
        "--profile",
        req.profile,
        "--yes",
    ]
    try:
        result = subprocess.run(  # noqa: S603
            cmd, capture_output=True, text=True, timeout=600,
        )
    except subprocess.TimeoutExpired:
        return {"status": "error", "detail": "Install timed out (10 min)"}

    if result.returncode != 0:
        return {
            "status": "error",
            "detail": result.stderr.strip()[:300] or "install failed",
        }

    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"status": "ok", "detail": result.stdout.strip()[:200]}
