"""Model management: inventory, detail, edit, delete, status, hfcard."""

import json
import re
import subprocess
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from .. import cli, config
from ..clusters import list_active
from ..model_variants import Backend, copy_backend_variant, migrate_backend_variant

router = APIRouter(prefix="/api", tags=["manage"])


# --- Audit ---


def _scan_orphaned() -> list[dict]:
    """Return accepted models whose files are not on disk."""
    if not config.ACCEPTED_DIR.exists():
        return []
    cached: set[tuple[str, str]] = set()
    cache = config.MODELS_CACHE_DIR
    if cache.exists():
        for repo_dir in cache.iterdir():
            snaps = repo_dir / "snapshots"
            if snaps.is_dir():
                for f in snaps.rglob("*"):
                    if f.is_file() or f.is_symlink():
                        cached.add((repo_dir.name, f.name))

    orphaned = []
    for path in sorted(config.ACCEPTED_DIR.glob("*.json")):
        if path.name == "default.json" or path.is_symlink():
            continue
        try:
            data = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        if data.get("model_path") or data.get("path"):
            downloaded = Path(str(data.get("model_path") or data.get("path"))).exists()
        else:
            repo = data.get("hf_repo") or data.get("repo")
            filename = data.get("hf_file")
            if repo and filename:
                repo_dir_name = f"models--{str(repo).replace('/', '--')}"
                downloaded = (repo_dir_name, filename) in cached
            else:
                downloaded = False
        if not downloaded:
            family = str(data.get("family", path.stem))
            orphaned.append(
                {
                    "family": family,
                    "alias": str(data.get("alias", family)),
                    "label": data.get("label") or None,
                    "model_name": str(data.get("model_name", family)),
                    "profile": str(data.get("profile", "")),
                }
            )
    return orphaned


@router.get("/models/audit")
async def audit_models():
    """List accepted-model registrations whose files are no longer on disk."""
    orphaned = _scan_orphaned()
    total = (
        sum(
            1
            for p in config.ACCEPTED_DIR.glob("*.json")
            if p.name != "default.json" and not p.is_symlink()
        )
        if config.ACCEPTED_DIR.exists()
        else 0
    )
    return {"orphaned": orphaned, "total": total}


@router.post("/models/audit")
async def cleanup_orphaned():
    """Delete accepted-model registrations for models no longer on disk."""
    orphaned = _scan_orphaned()
    deleted = []
    for m in orphaned:
        path = config.ACCEPTED_DIR / f"{m['family']}.json"
        if path.exists():
            path.unlink()
            _remove_model_state_references(m["family"], m["alias"])
            deleted.append(m["family"])
    return {"deleted": deleted, "count": len(deleted)}


# --- Inventory ---


_INVENTORY_SCRIPT = config.SCRIPTS_DIR / "model_inventory.py"


@router.get("/inventory")
async def get_inventory():
    """List all GGUF models on disk (cache dirs)."""
    try:
        result = subprocess.run(
            ["python3", str(_INVENTORY_SCRIPT)],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {"models": []}

    models = []
    for line in result.stdout.splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict) and item.get("repo"):
            models.append({str(k): str(v) for k, v in item.items()})
    models.sort(key=lambda m: m.get("repo", ""))
    return {"models": models}


# --- Backend variants ---


class CopyBackendRequest(BaseModel):
    backend: Backend
    overwrite: bool = False


def _safe_family(family: str) -> None:
    safe = re.compile(r"^[A-Za-z0-9_.-]+$")
    if not safe.fullmatch(family) or ".." in family:
        raise HTTPException(400, "invalid family name")


def _read_metadata_file(path):
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        raise HTTPException(500, "corrupt metadata")
    if not isinstance(data, dict):
        raise HTTPException(500, "invalid metadata")
    return data


@router.post("/models/{family}/copy-backend")
async def copy_model_backend(family: str, req: CopyBackendRequest):
    _safe_family(family)
    source_path = config.ACCEPTED_DIR / f"{family}.json"
    if not source_path.exists():
        raise HTTPException(404, f"family '{family}' not found")
    source = _read_metadata_file(source_path)
    copied = copy_backend_variant(source, req.backend)
    target_family = str(copied["family"])
    target_path = config.ACCEPTED_DIR / f"{target_family}.json"
    if target_path.exists() and not req.overwrite:
        raise HTTPException(409, f"backend variant '{target_family}' already exists")
    target_path.write_text(json.dumps(copied, indent=2, sort_keys=True) + "\n")
    return {"status": "copied", "family": target_family, "backend": req.backend}


@router.post("/models/migrate-backend-names")
async def migrate_backend_names():
    config.ACCEPTED_DIR.mkdir(parents=True, exist_ok=True)
    migrated: list[str] = []
    skipped: list[str] = []
    renamed: dict[str, str] = {}
    for source_path in sorted(config.ACCEPTED_DIR.glob("*.json")):
        if source_path.name == "default.json":
            continue
        source = _read_metadata_file(source_path)
        migrated_data = migrate_backend_variant(source)
        target_family = str(migrated_data["family"])
        if source_path.stem == target_family:
            skipped.append(target_family)
            continue
        target_path = config.ACCEPTED_DIR / f"{target_family}.json"
        if target_path.exists():
            skipped.append(source_path.stem)
            continue
        target_path.write_text(json.dumps(migrated_data, indent=2, sort_keys=True) + "\n")
        source_path.unlink()
        migrated.append(target_family)
        renamed[source_path.stem] = target_family
        old_alias = str(source.get("alias") or "")
        if old_alias:
            renamed[old_alias] = target_family
    for state_name in ("current-selection.json", "current-runner.json"):
        state_path = config.RUNS_DIR / state_name
        if not state_path.exists() or state_path.is_symlink():
            continue
        try:
            state = json.loads(state_path.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(state, dict):
            continue
        changed = False
        for field in ("model", "family"):
            value = state.get(field)
            if isinstance(value, str) and value in renamed:
                state[field] = renamed[value]
                changed = True
        if changed:
            tmp = state_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")
            tmp.replace(state_path)
    return {"status": "ok", "migrated": migrated, "skipped": skipped}


# --- Detail ---


@router.get("/models/{family}/detail")
async def model_detail(family: str):
    """Return full accepted metadata for a model family."""
    safe = re.compile(r"^[A-Za-z0-9_.-]+$")
    if not safe.fullmatch(family) or ".." in family:
        raise HTTPException(400, "invalid family name")

    path = config.ACCEPTED_DIR / f"{family}.json"
    if not path.exists():
        raise HTTPException(404, f"family '{family}' not found")
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError) as e:
        raise HTTPException(500, f"corrupt metadata: {e}")

    # Normalise nested mtp → flat for old accepted JSONs
    cfg = data.get("config") or {}
    if "mtp" in cfg and isinstance(cfg["mtp"], dict):
        mtp = cfg.pop("mtp")
        cfg["mtp_enabled"] = bool(mtp.get("enabled"))
        for k in ("draft_n_max", "draft_n_min", "draft_p_min"):
            if mtp.get(k) is not None:
                cfg[f"mtp_{k}"] = mtp[k]
        data["config"] = cfg

    return data


# --- Edit ---


class EditRequest(BaseModel):
    label: str | None = None
    profile: str | None = None
    ctx: int | None = None
    batch: int | None = None
    ubatch: int | None = None
    ngl: int | None = None
    cache_type_k: str | None = None
    cache_type_v: str | None = None
    ctx_shift: str | None = None
    reasoning: bool | None = None
    backend: str | None = None
    visible_devices: str | None = None
    split_mode: str | None = None
    tensor_split: str | None = None
    flags: str | None = None
    flash_attention: bool | None = None
    jinja: bool | None = None
    mtp_enabled: bool | None = None
    mtp_draft_n_max: int | None = None
    mtp_draft_n_min: int | None = None
    mtp_draft_p_min: float | None = None


@router.put("/models/{family}")
async def edit_model(family: str, req: EditRequest):
    """Edit accepted model config."""
    safe = re.compile(r"^[A-Za-z0-9_.-]+$")
    if not safe.fullmatch(family) or ".." in family:
        raise HTTPException(400, "invalid family name")

    path = config.ACCEPTED_DIR / f"{family}.json"
    if not path.exists():
        raise HTTPException(404, f"family '{family}' not found")

    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        raise HTTPException(500, "corrupt metadata")

    # Apply edits
    if req.label is not None:
        data["label"] = req.label.strip() or None
        if data["label"] is None:
            data.pop("label", None)
    if req.profile is not None:
        data["profile"] = req.profile
    cfg = data.setdefault("config", {})
    for field in (
        "ctx",
        "batch",
        "ubatch",
        "ngl",
        "cache_type_k",
        "cache_type_v",
        "ctx_shift",
        "visible_devices",
        "split_mode",
        "tensor_split",
        "flags",
    ):
        val = getattr(req, field, None)
        if val is not None:
            cfg[field] = val
    if req.reasoning is not None:
        cfg["reasoning"] = req.reasoning
        data["reasoning"] = req.reasoning
    if req.flash_attention is not None:
        cfg["flash_attention"] = req.flash_attention
    if req.jinja is not None:
        cfg["jinja"] = req.jinja
    if req.backend is not None:
        cfg["backend"] = req.backend
    cfg.pop("mtp", None)  # remove any old nested mtp block
    for field in ("mtp_enabled", "mtp_draft_n_max", "mtp_draft_n_min", "mtp_draft_p_min"):
        val = getattr(req, field, None)
        if val is not None:
            cfg[field] = val

    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    return {"status": "ok"}


# --- Delete ---


class DeleteRequest(BaseModel):
    repos: list[str]


def _metadata_matches_delete_id(data: dict, metadata_path: Path, value: str) -> bool:
    identifiers = {
        metadata_path.stem,
        str(data.get("family") or ""),
        str(data.get("alias") or ""),
        str(data.get("repo") or ""),
        str(data.get("hf_repo") or ""),
    }
    return value in identifiers


def _remove_model_state_references(family: str, alias: str) -> None:
    for state_name in ("current-selection.json", "current-runner.json"):
        state_path = config.RUNS_DIR / state_name
        if not state_path.exists() or state_path.is_symlink():
            continue
        try:
            state = json.loads(state_path.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(state, dict):
            continue
        if state.get("family") == family or state.get("model") in {family, alias}:
            state_path.unlink(missing_ok=True)
    default_path = config.ACCEPTED_DIR / "default.json"
    if default_path.exists() and not default_path.is_symlink():
        try:
            default_data = json.loads(default_path.read_text())
        except (json.JSONDecodeError, OSError):
            return
        if isinstance(default_data, dict) and default_data.get("family") == family:
            default_path.unlink(missing_ok=True)


def _delete_accepted_model(value: str) -> dict:
    for metadata_path in sorted(config.ACCEPTED_DIR.glob("*.json")):
        if metadata_path.name == "default.json" or metadata_path.is_symlink():
            continue
        data = _read_metadata_file(metadata_path)
        if not _metadata_matches_delete_id(data, metadata_path, value):
            continue
        family = str(data.get("family") or metadata_path.stem)
        alias = str(data.get("alias") or family)
        metadata_path.unlink()
        _remove_model_state_references(family, alias)
        return {"repo": value, "status": "deleted", "family": family}
    return {"repo": value, "status": "not_found"}


@router.post("/models/delete")
async def delete_models(req: DeleteRequest):
    """Delete one or more accepted models from local management state."""
    results = []
    for repo in req.repos:
        if not repo or len(repo) > 500:
            results.append({"repo": repo, "status": "error", "detail": "invalid repo"})
            continue
        results.append(_delete_accepted_model(repo))
    return {"results": results}


# --- Status ---


@router.get("/status")
async def full_status():
    """Full status dashboard: target, running model, accepted count, downloads."""
    config_file = config.RUNS_DIR / "config.json"
    target = "local"
    if config_file.exists():
        try:
            cfg = json.loads(config_file.read_text())
            target = cfg.get("target", "local")
        except (json.JSONDecodeError, OSError):
            pass

    active = list_active()
    running_list = [
        {
            "cluster_name": entry.get("cluster_name", ""),
            "family": entry.get("family") or entry.get("model") or "unknown",
            "profile": entry.get("profile", ""),
            "backend": entry.get("backend", ""),
        }
        for entry in active
    ]
    # Legacy single-runner field for backwards compat
    running_info = (
        {"status": "active", "family": running_list[0]["family"], "ctx": None}
        if running_list
        else {"status": "inactive", "family": None, "ctx": None}
    )

    accepted_count = 0
    if config.ACCEPTED_DIR.exists():
        accepted_count = sum(
            1
            for p in config.ACCEPTED_DIR.glob("*.json")
            if p.name != "default.json" and not p.is_symlink()
        )

    # Active downloads: in-process (backend installs) + CLI-spawned (bash huggingface-cli)
    downloads = [
        {"pid": "-", "repo": repo, "file": file} for repo, file in cli.active_downloads.items()
    ]
    try:
        result = subprocess.run(
            ["pgrep", "-af", "[h]f download|[h]uggingface.*download"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        for line in result.stdout.splitlines():
            parts = line.split()
            pid = parts[0] if parts else "?"
            repo = "?"
            if "download" in parts:
                idx = parts.index("download")
                if idx + 1 < len(parts):
                    repo = parts[idx + 1]
            if not any(d["repo"] == repo for d in downloads):
                downloads.append({"pid": pid, "repo": repo, "file": "?"})
    except (OSError, subprocess.TimeoutExpired):
        pass

    return {
        "target": target,
        "running": running_info,
        "running_clusters": running_list,
        "accepted_count": accepted_count,
        "default_set": (config.ACCEPTED_DIR / "default.json").exists(),
        "downloads": downloads,
    }


# --- HF Card ---


@router.get("/hfcard")
async def hf_card(repo: str = Query(..., min_length=1, max_length=500)):
    """Fetch HuggingFace model card as markdown."""
    try:
        result = subprocess.run(
            [
                "curl",
                "-s",
                "-L",
                "-H",
                "Accept: text/markdown",
                f"https://huggingface.co/{repo}/raw/main/README.md",
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {"markdown": "Failed to fetch model card.", "error": True}

    if result.returncode != 0 or not result.stdout.strip():
        return {"markdown": "No model card available.", "error": True}

    return {"markdown": result.stdout, "error": False}
