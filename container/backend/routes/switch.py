"""Model switching endpoint."""
import json
import re
from pathlib import Path
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from .. import config
from ..service import restart_llama_server

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


def _resolve_family_file(family: str, backend: str | None):
    """Find accepted metadata for family, optionally overriding backend."""
    safe_name = re.compile(r"[A-Za-z0-9_.-]+")

    if backend and backend not in ("rocm", "vulkan"):
        raise HTTPException(status_code=400, detail=f"invalid backend: {backend}")

    search_family = family
    if backend == "vulkan":
        search_family = f"{family}-vulkan"

    if (
        not safe_name.fullmatch(search_family)
        or ".." in search_family
        or search_family.startswith("-")
    ):
        raise HTTPException(status_code=400, detail="invalid family name")

    metadata_file = config.ACCEPTED_DIR / f"{search_family}.json"
    if not metadata_file.exists():
        raise HTTPException(
            status_code=404, detail=f"model family '{search_family}' not found"
        )

    data = _validate_accepted_path(metadata_file)
    if not data:
        raise HTTPException(status_code=500, detail="invalid accepted metadata")

    return metadata_file, data


@router.post("/switch", response_model=SwitchResponse)
async def switch_model(req: SwitchRequest):
    metadata_file, data = _resolve_family_file(req.family, req.backend)

    family = data.get("family", metadata_file.stem)
    alias = data.get("alias", data.get("model_name", family))
    profile = req.profile
    backend = data.get("backend", "rocm")
    remote_start = data.get("remote_start", f"./{metadata_file.stem}.sh")

    # Write current-model.env in llama.cpp dir
    env_file = config.LLAMA_CPP_DIR / "current-model.env"
    env_file.write_text(
        f"REMOTE_SCRIPT={remote_start}\n" f"REMOTE_PROFILE={profile}\n"
    )

    # Restart llama-server
    if not restart_llama_server():
        raise HTTPException(status_code=500, detail="failed to restart llama-server")

    return SwitchResponse(
        status="switched",
        family=str(family),
        profile=str(profile),
        alias=str(alias),
        backend=str(backend),
    )
