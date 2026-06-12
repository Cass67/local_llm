"""Model switching endpoint."""

import json
import re
import urllib.error
import urllib.request
from pathlib import Path
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from .. import config
from ..cli import run_stop_server

router = APIRouter(prefix="/api/models", tags=["switch"])


class SwitchRequest(BaseModel):
    family: str
    profile: str = "reliable"
    backend: str | None = None


class SwitchResponse(BaseModel):
    status: str
    family: str
    profile: str
    alias: str
    backend: str


def _validate_accepted_path(path: Path) -> dict | None:  # noqa: DOC502
    if path.is_symlink() or not path.is_file():
        return None
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def get_llama_swap_model_ids() -> list[str]:
    """Return llama-swap model IDs from /v1/models."""
    try:
        with urllib.request.urlopen(f"{config.LLAMA_SWAP_URL}/v1/models", timeout=5) as response:
            body = json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError):
        return []
    data = body.get("data") if isinstance(body, dict) else []
    if not isinstance(data, list):
        return []
    return [str(item["id"]) for item in data if isinstance(item, dict) and item.get("id")]


def get_llama_swap_running_ids() -> list[str]:
    """Return running llama-swap model IDs from /running."""
    try:
        with urllib.request.urlopen(f"{config.LLAMA_SWAP_URL}/running", timeout=5) as response:
            body = json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError):
        return []
    running = body.get("running") if isinstance(body, dict) else []
    if not isinstance(running, list):
        return []
    ids: list[str] = []
    for item in running:
        if isinstance(item, str):
            ids.append(item)
        elif isinstance(item, dict) and item.get("id"):
            ids.append(str(item["id"]))
        elif isinstance(item, dict) and item.get("model"):
            ids.append(str(item["model"]))
    return ids


def _quant_suffix(data: dict) -> str | None:
    raw = str(data.get("quant") or (data.get("config") or {}).get("quant") or data.get("hf_file") or "").lower()
    if "q6" in raw:
        return "q6"
    if "q5_k_m" in raw or "q5km" in raw:
        return "q5km"
    if "q5_k_s" in raw or "q5ks" in raw:
        return "q5ks"
    return None


def _llama_swap_id_for(data: dict, metadata_file: Path, available_ids: list[str]) -> str:
    family = str(data.get("family") or metadata_file.stem)
    alias = str(data.get("alias") or data.get("model_name") or family)
    normalized_family = family.replace("-heretic", "")
    normalized_alias = alias.replace("-heretic", "")
    candidates = [family, alias, normalized_family, normalized_alias]
    suffix = _quant_suffix(data)
    if suffix and normalized_family == "qwen3.6-27b":
        candidates.append(f"qwen3.6-27b-{suffix}")
    if suffix and normalized_family.endswith("-1gpu"):
        base = normalized_family.removesuffix("-1gpu")
        if not base.endswith(f"-{suffix}"):
            candidates.append(f"{base}-{suffix}-1gpu")
    for candidate in candidates:
        if candidate in available_ids:
            return candidate
    raise HTTPException(
        status_code=409,
        detail=f"model '{family}' is not configured in llama-swap; available: {', '.join(available_ids)}",
    )


def _write_selection(model_id: str, family: str, profile: str, backend: str) -> None:
    config.RUNS_DIR.mkdir(parents=True, exist_ok=True)
    path = config.RUNS_DIR / "current-selection.json"
    path.write_text(json.dumps({
        "model": model_id,
        "family": family,
        "profile": profile,
        "backend": backend,
    }, indent=2, sort_keys=True) + "\n")


def _read_selection() -> dict | None:
    path = config.RUNS_DIR / "current-selection.json"
    if not path.exists() or path.is_symlink():
        return None
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _resolve_family_file(family: str, backend: str | None):
    """Find accepted metadata for family, optionally overriding backend."""
    safe_name = re.compile(r"[A-Za-z0-9_.-]+")

    if backend and backend not in ("rocm", "vulkan"):
        raise HTTPException(status_code=400, detail=f"invalid backend: {backend}")

    search_family = family
    if backend == "vulkan" and (config.ACCEPTED_DIR / f"{family}-vulkan.json").exists():
        search_family = f"{family}-vulkan"

    if (
        not safe_name.fullmatch(search_family)
        or ".." in search_family
        or search_family.startswith("-")
    ):
        raise HTTPException(status_code=400, detail="invalid family name")

    metadata_file = config.ACCEPTED_DIR / f"{search_family}.json"
    if not metadata_file.exists():
        raise HTTPException(status_code=404, detail=f"model family '{search_family}' not found")

    data = _validate_accepted_path(metadata_file)
    if not data:
        raise HTTPException(status_code=500, detail="invalid accepted metadata")

    return metadata_file, data


@router.post("/switch", response_model=SwitchResponse)
async def switch_model(req: SwitchRequest):
    metadata_file, data = _resolve_family_file(req.family, req.backend)

    family = data.get("family", metadata_file.stem)
    profile = req.profile
    backend = str((data.get("config") or {}).get("backend") or data.get("backend", "rocm"))
    available_ids = get_llama_swap_model_ids()
    model_id = _llama_swap_id_for(data, metadata_file, available_ids)
    _write_selection(model_id, str(family), str(profile), backend)

    return SwitchResponse(
        status="selected",
        family=str(family),
        profile=str(profile),
        alias=model_id,
        backend=backend,
    )


@router.post("/stop")
async def stop_model_server():
    """Stop llama-server.service."""
    return {"status": run_stop_server()}


@router.get("/current")
async def current_model():
    """Return selected/running llama-swap model."""
    selection = _read_selection() or {}
    selected_model = str(selection.get("model") or "unknown")
    running_ids = get_llama_swap_running_ids()
    running = selected_model in running_ids if selected_model != "unknown" else bool(running_ids)
    return {
        "family": selection.get("family", selected_model),
        "profile": selection.get("profile", "unknown"),
        "alias": selected_model,
        "backend": selection.get("backend", "unknown"),
        "running": running,
        "llama_server": {"status": "llama-swap", "running": running_ids},
    }
