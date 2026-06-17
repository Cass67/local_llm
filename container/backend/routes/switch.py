"""Model lookup utilities and current-state endpoint."""

import json
import re
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import active_runners, config
from ..runtime import DockerRunnerConfig

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


def _resolve_model_id_file(model_id: str):
    safe_name = re.compile(r"[A-Za-z0-9_.-]+")
    if not safe_name.fullmatch(model_id) or ".." in model_id or model_id.startswith("-"):
        raise HTTPException(status_code=400, detail="invalid model id")
    for metadata_file in sorted(config.ACCEPTED_DIR.glob("*.json")):
        if metadata_file.name == "default.json":
            continue
        data = _validate_accepted_path(metadata_file)
        if not data:
            continue
        aliases = {metadata_file.stem, str(data.get("family", "")), str(data.get("alias", ""))}
        if model_id in aliases:
            return metadata_file, data
    raise HTTPException(status_code=404, detail=f"model '{model_id}' not found")


def _resolve_family_file(family: str, backend: str | None):
    """Find accepted metadata for family, optionally overriding backend."""
    safe_name = re.compile(r"[A-Za-z0-9_.-]+")

    if backend and backend not in ("rocm", "vulkan", "cuda"):
        raise HTTPException(status_code=400, detail=f"invalid backend: {backend}")

    search_family = family
    if (
        backend in ("vulkan", "cuda")
        and (config.ACCEPTED_DIR / f"{family}-{backend}.json").exists()
    ):
        search_family = f"{family}-{backend}"

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
async def switch_model(_req: SwitchRequest):
    """Legacy single-model switch. Use POST /api/clusters/{id}/start instead."""
    raise HTTPException(
        status_code=501,
        detail=(
            "Direct model switching is no longer supported. "
            "Create a GPU cluster on the Architecture tab and use "
            "POST /api/clusters/{id}/start to launch a model on it."
        ),
    )


def _native_process_on_runner_port() -> bool:
    """Return True if something occupies the base runner port outside Docker."""
    import socket as _socket

    port = DockerRunnerConfig().port
    occupied = False
    with _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        try:
            s.connect(("127.0.0.1", port))
            occupied = True
        except OSError:
            pass
    if not occupied:
        return False
    # Check if it's one of our managed runners
    for entry in active_runners.list_active():
        if entry.get("port") == port:
            return False
    return True


@router.get("/current")
async def current_model():
    """Return currently active model instances across all clusters."""
    active = active_runners.list_active()
    native_warning = _native_process_on_runner_port() if not active else False

    if not active:
        return {
            "family": "none",
            "profile": "none",
            "alias": "none",
            "backend": "none",
            "running": False,
            "native_process_warning": native_warning,
            "llama_server": {"status": "idle", "running": []},
            "instances": [],
        }

    # Backward-compat: expose the first active instance as the "current" model
    first = active[0]
    return {
        "family": first.get("family", "unknown"),
        "profile": first.get("profile", "unknown"),
        "alias": first.get("model", "unknown"),
        "backend": first.get("backend", "unknown"),
        "running": True,
        "native_process_warning": native_warning,
        "llama_server": {
            "status": "local-llm-runner",
            "running": [e.get("model") for e in active if e.get("model")],
        },
        "instances": active,
    }
