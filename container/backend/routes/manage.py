"""Model management: inventory, detail, edit, delete, status, hfcard."""
import json
import re
import subprocess
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from .. import config, cli
from ..service import detect_running_model

router = APIRouter(prefix="/api", tags=["manage"])


# --- Inventory ---

@router.get("/inventory")
async def get_inventory():
    """List all GGUF models on disk (cache dirs)."""
    script = r"""
import json, pathlib, subprocess
roots=[pathlib.Path.home()/'.cache'/'huggingface'/'hub', pathlib.Path.home()/'.cache'/'local_llm'/'models', pathlib.Path.home()/'.cache'/'llama.cpp']
for root in roots:
    if not root.is_dir():
        continue
    for repo_dir in sorted(root.glob('models--*')):
        if not repo_dir.is_dir():
            continue
        repo=repo_dir.name.removeprefix('models--').replace('--','/',1)
        ggufs=sorted(p for p in repo_dir.rglob('*.gguf') if not p.name.lower().startswith('mmproj'))
        path=str(ggufs[0] if ggufs else repo_dir)
        try:
            size=int(subprocess.check_output(['du','-sb',str(repo_dir)], text=True).split()[0])
        except (subprocess.SubprocessError, ValueError, OSError):
            size=0
        print(json.dumps({
            'repo': repo, 'path': path,
            'file': pathlib.Path(path).name,
            'disk_gb': f'{size/1_000_000_000:.1f}' if size else '-',
            'gguf': 'yes' if ggufs else 'no',
        }))
"""
    try:
        result = subprocess.run(
            ["python3", "-c", script],
            capture_output=True, text=True, timeout=30,
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

    return data


# --- Edit ---

class EditRequest(BaseModel):
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


@router.put("/models/{family}")
async def edit_model(family: str, req: EditRequest):
    """Edit accepted model config. Writes metadata + regenerates launcher."""
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
    if req.profile is not None:
        data["profile"] = req.profile
    cfg = data.setdefault("config", {})
    for field in (
        "ctx", "batch", "ubatch", "ngl", "cache_type_k", "cache_type_v",
        "ctx_shift", "visible_devices", "split_mode", "tensor_split", "flags",
    ):
        val = getattr(req, field, None)
        if val is not None:
            cfg[field] = val
    if req.reasoning is not None:
        cfg["reasoning"] = req.reasoning
    if req.backend is not None:
        cfg["backend"] = req.backend

    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")

    # Regenerate launcher
    launcher_result = cli.run_update_launcher(family)
    return {"status": "ok", "launcher": launcher_result}


# --- Delete ---

class DeleteRequest(BaseModel):
    repos: list[str]


@router.post("/models/delete")
async def delete_models(req: DeleteRequest):
    """Delete one or more model repos."""
    target = "local"
    results = []
    for repo in req.repos:
        if not repo or len(repo) > 500:
            results.append({"repo": repo, "status": "error", "detail": "invalid repo"})
            continue
        result = cli.run_delete(repo, target)
        results.append({"repo": repo, "status": result})
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

    running_info = detect_running_model()

    accepted_count = 0
    if config.ACCEPTED_DIR.exists():
        accepted_count = sum(
            1 for p in config.ACCEPTED_DIR.glob("*.json")
            if p.name != "default.json" and not p.is_symlink()
        )

    # Active downloads
    downloads = []
    try:
        result = subprocess.run(
            ["pgrep", "-af", "[h]f download|[h]uggingface.*download"],
            capture_output=True, text=True, timeout=5,
        )
        for line in result.stdout.splitlines():
            parts = line.split()
            pid = parts[0] if parts else "?"
            repo = "?"
            if "download" in parts:
                idx = parts.index("download")
                if idx + 1 < len(parts):
                    repo = parts[idx + 1]
            downloads.append({"pid": pid, "repo": repo})
    except (OSError, subprocess.TimeoutExpired):
        pass

    return {
        "target": target,
        "running": running_info,
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
                "curl", "-s", "-L", "-H", "Accept: text/markdown",
                f"https://huggingface.co/{repo}/raw/main/README.md",
            ],
            capture_output=True, text=True, timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {"markdown": "Failed to fetch model card.", "error": True}

    if result.returncode != 0 or not result.stdout.strip():
        return {"markdown": "No model card available.", "error": True}

    return {"markdown": result.stdout, "error": False}
