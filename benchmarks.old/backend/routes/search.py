"""Search and install endpoints."""

import asyncio
import json
from pathlib import Path

from fastapi import APIRouter, Query
from pydantic import BaseModel
from .. import cli, config

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


class CancelRequest(BaseModel):
    repo: str


@router.post("/cancel")
async def cancel_download(req: CancelRequest):
    ok = cli.cancel_download(req.repo)
    return {"cancelled": ok}


@router.get("/progress")
async def download_progress():
    """Current download progress for all active installs."""
    return {"progress": cli.download_progress}


@router.get("/unregistered")
def unregistered_models():
    """Models in HF cache that have no accepted JSON entry."""
    accepted_repos: set[str] = set()
    if config.ACCEPTED_DIR.exists():
        for p in config.ACCEPTED_DIR.glob("*.json"):
            if p.name == "default.json":
                continue
            try:
                data = json.loads(p.read_text())
                repo = data.get("hf_repo") or data.get("repo")
                if repo:
                    accepted_repos.add(str(repo))
            except (OSError, json.JSONDecodeError):
                pass

    result = []
    cache = config.MODELS_CACHE_DIR
    if not cache.exists():
        return {"models": result}
    for repo_dir in sorted(cache.iterdir()):
        if not repo_dir.name.startswith("models--"):
            continue
        repo = repo_dir.name.removeprefix("models--").replace("--", "/", 1)
        if repo in accepted_repos:
            continue
        snaps = repo_dir / "snapshots"
        if not snaps.is_dir():
            continue
        ggufs = [
            f
            for f in snaps.rglob("*.gguf")
            if not f.name.lower().startswith("mmproj") and (f.is_file() or f.is_symlink())
        ]
        if not ggufs:
            continue
        ggufs.sort(key=lambda f: f.stat().st_size if f.exists() else 0, reverse=True)
        result.append({"repo": repo, "file": ggufs[0].name, "path": str(ggufs[0])})
    return {"models": result}


class AcceptRequest(BaseModel):
    repo: str
    file: str
    path: str


@router.post("/accept")
def accept_model(req: AcceptRequest):
    """Write accepted metadata for a model already present in the cache."""
    model_id = cli._model_id(req.repo, req.file)
    cli._write_installed_metadata(model_id, req.repo, req.file, "balanced", 65536, Path(req.path))
    return {"status": "accepted", "family": model_id}
