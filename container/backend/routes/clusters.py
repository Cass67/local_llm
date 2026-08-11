"""GPU cluster management: inventory, cluster CRUD, start/stop per cluster."""

import asyncio
import json
from dataclasses import asdict

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import active_runners, config, startup_progress
from ..clusters import (
    ClusterDef,
    create_cluster,
    delete_cluster,
    get_cluster,
    list_clusters,
    read_active,
    read_desired,
    remove_active,
)
from ..gpu_inventory import GpuInfo, detect_gpus

router = APIRouter(prefix="/api", tags=["clusters"])


# --- GPU inventory ---


@router.get("/gpus")
async def gpus():
    """Detect and return physical GPUs with per-backend device indices."""
    inventory: list[GpuInfo] = await asyncio.to_thread(detect_gpus)
    return {
        "gpus": [
            {
                "pci_id": g.pci_id,
                "vendor": g.vendor,
                "model_name": g.model_name,
                "board": g.board,
                "vram_mb": g.vram_mb,
                "rocm_index": g.rocm_index,
                "cuda_index": g.cuda_index,
                "vulkan_index": g.vulkan_index,
            }
            for g in inventory
        ]
    }


# --- Cluster CRUD ---


class CreateClusterRequest(BaseModel):
    name: str
    gpu_pci_ids: list[str]
    backend: str


def _cluster_with_status(cluster: ClusterDef) -> dict:
    active = read_active(cluster.id)
    desired = read_desired(cluster.id)
    running = active_runners.is_running(cluster) if active else False
    return {
        **asdict(cluster),
        "active": {
            "model": active.get("model"),
            "family": active.get("family"),
            "label": active.get("label"),
            "profile": active.get("profile"),
            "running": running,
            "warnings": active.get("warnings") or [],
        }
        if active
        else None,
        "desired": {
            "family": desired.get("family"),
            "profile": desired.get("profile", "reliable"),
        }
        if desired
        else None,
        # Cold-start stage, so the UI polling this endpoint sees progress while the
        # start request it fired is still open.
        "startup": startup_progress.get(cluster.id),
    }


@router.get("/clusters")
async def get_clusters():
    clusters = list_clusters()
    return {"clusters": [_cluster_with_status(c) for c in clusters]}


@router.post("/clusters")
async def post_cluster(req: CreateClusterRequest):
    inventory = await asyncio.to_thread(detect_gpus)
    try:
        cluster = create_cluster(req.name, req.gpu_pci_ids, req.backend, inventory)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return asdict(cluster)


@router.delete("/clusters/{cluster_id}")
async def del_cluster(cluster_id: str):
    cluster = get_cluster(cluster_id)
    if not cluster:
        raise HTTPException(status_code=404, detail="cluster not found")
    if active_runners.is_running(cluster):
        raise HTTPException(status_code=409, detail="stop the cluster before deleting it")
    remove_active(cluster_id)
    delete_cluster(cluster_id)
    return {"status": "deleted"}


# --- Per-cluster start/stop ---


class StartRequest(BaseModel):
    family: str
    profile: str = ""  # empty = use saved default for this family


def _default_profile(family: str) -> str:
    try:
        data = json.loads(config.PROFILES_CONFIG.read_text())
        fam = data.get("families", {}).get(family, {})
        # An empty default used to fall through to the literal "balanced", which silently
        # applies nothing when the family names its profiles anything else.
        return fam.get("default", "") or next(iter(fam.get("profiles", {})), "balanced")
    except (OSError, json.JSONDecodeError):
        return "balanced"


def _resolve_accepted(family: str) -> dict:
    safe = __import__("re").compile(r"[A-Za-z0-9_.-]+")
    if not safe.fullmatch(family) or ".." in family:
        raise HTTPException(status_code=400, detail="invalid family name")
    path = config.ACCEPTED_DIR / f"{family}.json"
    if not path.exists() or path.is_symlink():
        raise HTTPException(status_code=404, detail=f"model family '{family}' not found")
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail="corrupt model metadata") from exc
    if not isinstance(data, dict):
        raise HTTPException(status_code=500, detail="invalid model metadata")
    return data


@router.post("/clusters/{cluster_id}/start")
async def start_cluster(cluster_id: str, req: StartRequest):
    cluster = get_cluster(cluster_id)
    if not cluster:
        raise HTTPException(status_code=404, detail="cluster not found")
    accepted = _resolve_accepted(req.family)
    # Use saved default profile if none specified
    profile = req.profile or _default_profile(req.family)
    accepted["profile"] = profile
    try:
        await asyncio.to_thread(active_runners.start, cluster, accepted)
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=502, detail=f"failed to launch runner: {exc}") from exc
    active = read_active(cluster_id)
    return {"status": "running", "cluster_id": cluster_id, "model": active and active.get("model")}


@router.post("/clusters/{cluster_id}/stop")
async def stop_cluster(cluster_id: str):
    cluster = get_cluster(cluster_id)
    if not cluster:
        raise HTTPException(status_code=404, detail="cluster not found")
    await asyncio.to_thread(active_runners.stop, cluster)
    # Drop the finished-launch entry so a stopped cluster does not keep reporting
    # the "ready" of a runner that no longer exists.
    startup_progress.clear(cluster_id)
    return {"status": "stopped", "cluster_id": cluster_id}
