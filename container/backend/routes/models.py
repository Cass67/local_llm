"""Model listing endpoint."""

import json
from pathlib import Path

from fastapi import APIRouter

from .. import config
from ..models import ModelConfig, ModelInfo, ModelListResponse

router = APIRouter(prefix="/api", tags=["models"])


def _snapshot_files() -> set[tuple[str, str]]:
    """Return {(repo_dir_name, filename)} for all files under MODELS_CACHE_DIR snapshots."""
    result: set[tuple[str, str]] = set()
    cache = config.MODELS_CACHE_DIR
    if not cache.exists():
        return result
    for repo_dir in cache.iterdir():
        snaps = repo_dir / "snapshots"
        if not snaps.is_dir():
            continue
        for f in snaps.rglob("*"):
            if f.is_file() or f.is_symlink():
                result.add((repo_dir.name, f.name))
    return result


def _is_downloaded(data: dict, cached: set[tuple[str, str]]) -> bool:
    if data.get("model_path") or data.get("path"):
        return Path(str(data.get("model_path") or data.get("path"))).exists()
    repo = data.get("hf_repo") or data.get("repo")
    filename = data.get("hf_file")
    if repo and filename:
        repo_dir = f"models--{str(repo).replace('/', '--')}"
        return (repo_dir, filename) in cached
    return False


def _read_accepted_models() -> list[ModelInfo]:
    models: list[ModelInfo] = []
    if not config.ACCEPTED_DIR.exists():
        return models

    cached = _snapshot_files()
    for path in sorted(config.ACCEPTED_DIR.glob("*.json")):
        if path.name == "default.json":
            continue
        try:
            data = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue

        family = data.get("family", path.stem)
        alias = data.get("alias", data.get("model_name", family))
        config_data = data.get("config") or {}
        model_cfg = ModelConfig(
            quant=config_data.get("quant"),
            batch=config_data.get("batch", 4096),
            ubatch=config_data.get("ubatch", 256),
            ngl=config_data.get("ngl", 999),
            visible_devices=config_data.get("visible_devices"),
            split_mode=config_data.get("split_mode"),
            tensor_split=config_data.get("tensor_split"),
        )

        downloaded = _is_downloaded(data, cached)

        # Profile is authoritative — prefer its context over the accepted model JSON
        context = None
        try:
            profiles = json.loads(config.PROFILES_CONFIG.read_text())
            fam_data = profiles.get("families", {}).get(str(family), {})
            profile_name = str(data.get("profile", "reliable"))
            profile_cfg = fam_data.get("profiles", {}).get(profile_name, {})
            context = profile_cfg.get("context")
        except (OSError, json.JSONDecodeError, AttributeError):
            pass
        if context is None:
            context = data.get("context")

        models.append(
            ModelInfo(
                family=str(family),
                alias=str(alias),
                model_name=str(data.get("model_name", family)),
                label=data.get("label") or None,
                profile=str(data.get("profile", "reliable")),
                context=context,
                backend=str(data.get("backend") or config_data.get("backend", "rocm")),
                reasoning=bool(data.get("reasoning", False)),
                config=model_cfg,
                running=False,
                downloaded=downloaded,
            )
        )
    return models


@router.get("/models", response_model=ModelListResponse)
async def list_models():
    models = _read_accepted_models()
    return ModelListResponse(models=models)
