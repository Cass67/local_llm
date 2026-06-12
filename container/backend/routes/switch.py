"""Model switching endpoint."""

import json
import re
import time
import http.client
import urllib.error
import urllib.parse
from pathlib import Path
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from .. import config
from ..cli import run_stop_server
from ..runtime import DockerRunner, DockerRunnerConfig, build_runner_container_spec

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


def _write_selection(model_id: str, family: str, profile: str, backend: str) -> None:
    config.RUNS_DIR.mkdir(parents=True, exist_ok=True)
    path = config.RUNS_DIR / "current-selection.json"
    path.write_text(
        json.dumps(
            {
                "model": model_id,
                "family": family,
                "profile": profile,
                "backend": backend,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )


def _write_runner_state(model_id: str, metadata: dict, profile: str, backend: str) -> None:
    config.RUNS_DIR.mkdir(parents=True, exist_ok=True)
    spec = build_runner_container_spec(metadata, DockerRunnerConfig(), config.MODELS_CACHE_DIR)
    path = config.RUNS_DIR / "current-runner.json"
    path.write_text(
        json.dumps(
            {
                "model": model_id,
                "family": metadata.get("family", model_id),
                "profile": profile,
                "backend": backend,
                "container": {
                    "name": spec.name,
                    "image": spec.image,
                    "command": spec.command,
                    "ports": spec.ports,
                    "devices": spec.devices,
                    "group_add": spec.group_add,
                    "environment": spec.environment,
                },
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )


def _read_runner_state() -> dict | None:
    path = config.RUNS_DIR / "current-runner.json"
    if not path.exists() or path.is_symlink():
        return None
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _read_selection() -> dict | None:
    path = config.RUNS_DIR / "current-selection.json"
    if not path.exists() or path.is_symlink():
        return None
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _wait_for_runner_ready(runner: DockerRunner, timeout_seconds: float = 120.0) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if not runner.is_running():
            return False
        try:
            parsed = urllib.parse.urlparse(f"{config.RUNNER_URL}/models")
            if parsed.scheme != "http" or not parsed.hostname:
                return False
            conn = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=2)
            conn.request("GET", parsed.path)
            response = conn.getresponse()
            try:
                if response.status == 200:
                    return True
            finally:
                conn.close()
        except (OSError, urllib.error.URLError):
            pass
        time.sleep(1)
    return False


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


def _launch_model(metadata_file: Path, data: dict, profile: str) -> str:
    family = data.get("family", metadata_file.stem)
    backend = str((data.get("config") or {}).get("backend") or data.get("backend", "rocm"))
    model_id = str(data.get("alias") or family)
    _write_selection(model_id, str(family), str(profile), backend)
    runner = DockerRunner(
        DockerRunnerConfig(image=config.RUNNER_IMAGE, socket_path=config.DOCKER_SOCKET),
        models_dir=config.MODELS_CACHE_DIR,
        host_models_dir=config.HOST_MODELS_CACHE_DIR,
    )
    runner.launch(data)
    if not _wait_for_runner_ready(runner):
        detail = "\n".join(runner.logs(40)) or "runner did not become ready"
        raise RuntimeError(detail[-1000:])
    _write_runner_state(model_id, data, str(profile), backend)
    return model_id


def switch_model_by_id(model_id: str) -> None:
    metadata_file, data = _resolve_model_id_file(model_id)
    profile = str(data.get("profile") or "reliable")
    _launch_model(metadata_file, data, profile)


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
    try:
        model_id = _launch_model(metadata_file, data, str(profile))
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(
            status_code=502, detail=f"failed to launch local runner: {exc}"
        ) from exc

    return SwitchResponse(
        status="loaded",
        family=str(family),
        profile=str(profile),
        alias=model_id,
        backend=backend,
    )


@router.post("/stop")
async def stop_model_server():
    """Stop host llama-server service if present."""
    return {"status": run_stop_server()}


@router.get("/current")
async def current_model():
    """Return selected project-owned runner model."""
    selection = _read_selection() or {}
    runner = _read_runner_state() or {}
    current_model = str(runner.get("model") or selection.get("model") or "unknown")
    running = current_model != "unknown" and bool(runner)
    family = runner.get("family") or selection.get("family", current_model)
    profile = runner.get("profile") or selection.get("profile", "unknown")
    backend = runner.get("backend") or selection.get("backend", "unknown")
    return {
        "family": family,
        "profile": profile,
        "alias": current_model,
        "backend": backend,
        "running": running,
        "llama_server": {
            "status": "local-llm-runner",
            "running": [current_model] if running else [],
        },
    }
