"""Model listing endpoint."""

import json
from pathlib import Path

from fastapi import APIRouter

from .. import config
from ..models import ModelConfig, ModelInfo, ModelListResponse

router = APIRouter(prefix="/api", tags=["models"])


def output_limit(context: int | None) -> int:
    """Max generation budget to advertise.

    llama-server has no separate output window — prompt and generation share the
    context — but harnesses need a number. Report 0/absent and they fall back to
    their own small default (a few thousand tokens) and truncate long replies
    with "reached the maximum output token limit".

    Capped at 49152 rather than half the window. Harnesses differ in what they do
    with this number: model-switch treats it as a ceiling on one reply and derives
    a separate, smaller compaction reserve, but Forge subtracts it from the context
    on every turn. At ctx 256000 the old half-window value of 128000 therefore cost
    Forge half its usable prompt budget and made it compact at ~140k. 49152 is
    RESERVE_FLOOR in scripts/model-switch.py — the value that has held up there —
    and is still far beyond any real single reply.
    """
    return min((context or 131072) // 2, 49152)


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
            fam_profiles = fam_data.get("profiles", {})
            profile_name = str(data.get("profile", "reliable"))
            # The accepted JSON can name a profile the family no longer defines
            # (e.g. renamed to "rccl"); fall back to the family default rather
            # than reporting the stale context from the accepted JSON.
            if profile_name not in fam_profiles:
                profile_name = str(fam_data.get("default", profile_name))
            profile_cfg = fam_profiles.get(profile_name, {})
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
