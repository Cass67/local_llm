"""CLI wrapper: subprocess calls to model-manager scripts."""

import importlib
import json
import os
import re
import subprocess
import time
from pathlib import Path

from . import config
from .config import SCRIPTS_DIR

MODEL_DISCOVERY = SCRIPTS_DIR / "model-discovery.sh"
MODEL_MANAGER = SCRIPTS_DIR / "model-manager.sh"
MODEL_FIT = SCRIPTS_DIR / "model-fit.py"
OC_LOCAL = SCRIPTS_DIR / "oc-local"


def run_discovery(query: str, host: str | None = None, limit: int = 30) -> list[dict]:
    """Run model-discovery.sh, return ranked candidates."""
    cmd = [str(MODEL_DISCOVERY)]
    if host:
        cmd.extend(["--host", host])
    else:
        cmd.append("--local")
    cmd.extend(["--query", query, "--limit", str(limit), "--json"])

    result = subprocess.run(  # noqa: S603
        cmd,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip()[:300] or "discovery failed")

    data = json.loads(result.stdout)
    return data.get("candidates", [])


def _quant_suffix(file: str) -> str:
    normalized = file.lower().replace("_", "")
    if "q6k" in normalized or "q6" in normalized:
        return "q6"
    if "q5km" in normalized:
        return "q5km"
    if "q5ks" in normalized:
        return "q5ks"
    if "q4km" in normalized:
        return "q4km"
    return "gguf"


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9_.-]+", "-", value.lower()).strip("-.")
    return re.sub(r"-+", "-", slug) or "model"


def _model_id(repo: str, file: str) -> str:
    base = repo.rsplit("/", 1)[-1]
    base = re.sub(r"-?gguf$", "", base, flags=re.IGNORECASE)
    suffix = _quant_suffix(file)
    slug = _slug(base)
    return slug if slug.endswith(f"-{suffix}") else f"{slug}-{suffix}"


def _write_installed_metadata(
    model_id: str, repo: str, file: str, profile: str, ctx: int, model_path: Path
) -> None:
    config.ACCEPTED_DIR.mkdir(parents=True, exist_ok=True)
    metadata = {
        "family": model_id,
        "alias": model_id,
        "model_name": repo.rsplit("/", 1)[-1].removesuffix("-GGUF"),
        "repo": repo,
        "hf_repo": repo,
        "hf_file": file,
        "model_path": str(model_path),
        "profile": profile,
        "context": ctx,
        "backend": "vulkan",
        "reasoning": False,
        "config": {
            "backend": "vulkan",
            "quant": _quant_suffix(file),
            "batch": 4096,
            "ubatch": 256,
            "ngl": 999,
            "ctx": ctx,
            "visible_devices": "0,1",
            "split_mode": "layer",
            "tensor_split": "1,1",
        },
    }
    (config.ACCEPTED_DIR / f"{model_id}.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n"
    )


def _install_error(
    phase: str,
    repo: str,
    file: str,
    profile: str,
    detail: str,
    logs: list[str],
) -> dict:
    clean_detail = detail[:500]
    return {
        "status": "error",
        "phase": phase,
        "repo": repo,
        "file": file,
        "profile": profile,
        "detail": f"{phase} failed for {repo} / {file}: {clean_detail}",
        "logs": [*logs, f"{phase} failed: {clean_detail}"],
    }


def run_install(repo: str, file: str, profile: str) -> dict:
    """Install model into host HF cache and write project-owned accepted metadata."""
    os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
    logs = [f"install {profile}: {repo} / {file}"]
    try:
        huggingface_hub = importlib.import_module("huggingface_hub")
        hf_hub_download = getattr(huggingface_hub, "hf_hub_download")
    except (ImportError, AttributeError):
        return _install_error(
            "prepare", repo, file, profile, "huggingface_hub is not installed", logs
        )

    ctx = 65536
    model_id = _model_id(repo, file)
    try:
        downloaded = hf_hub_download(repo_id=repo, filename=file, cache_dir=config.MODELS_CACHE_DIR)
        model_path = Path(downloaded)
    except Exception as exc:
        return _install_error("download", repo, file, profile, str(exc), logs)

    try:
        _write_installed_metadata(model_id, repo, file, profile, ctx, model_path)
    except Exception as exc:
        return _install_error("metadata", repo, file, profile, str(exc), logs)

    return {
        "status": "installed",
        "family": model_id,
        "alias": model_id,
        "path": str(model_path),
    }


def run_delete(repo: str, target: str) -> str:
    """Delete model via model-manager.sh delete."""
    cmd = ["bash", str(MODEL_MANAGER), "delete", repo, "--target", target, "--yes"]
    result = subprocess.run(  # noqa: S603
        cmd,
        capture_output=True,
        text=True,
        timeout=300,
    )
    if result.returncode == 0:
        return "ok"
    return f"error: {result.stderr.strip()[:200]}"


def run_update_launcher(family: str) -> str:
    """Regenerate launcher for family."""
    cmd = [str(MODEL_MANAGER), "update-launcher", "--family", family, "--yes"]
    result = subprocess.run(  # noqa: S603
        cmd,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode == 0:
        return "ok"
    return f"warning: {(result.stderr or result.stdout or '').strip()[:200]}"


def run_start_server(family: str, profile: str, ctx_override: str | None = None) -> tuple[str, str]:
    """Start server via oc-local."""
    if not OC_LOCAL.exists():
        return "error", "oc-local not found"

    cmd = ["bash", str(OC_LOCAL), family, profile]
    if ctx_override:
        cmd.extend(["--ctx", ctx_override])

    try:
        process = subprocess.Popen(  # noqa: S603
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        deadline = time.monotonic() + 120
        last_stderr = ""
        while time.monotonic() < deadline:
            if process.poll() is not None:
                _, stderr = process.communicate(timeout=1)
                last_stderr = stderr.strip()
                break
            time.sleep(1)
        if process.returncode and process.returncode != 0:
            return "error", last_stderr[:200] or "oc-local exited with error"
        return "ok", "Server started"
    except (subprocess.SubprocessError, OSError) as e:
        return "error", str(e)


def run_stop_server() -> str:
    """Stop llama-server via systemctl."""
    try:
        result = subprocess.run(
            ["systemctl", "--user", "stop", "llama-server.service"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        return "ok" if result.returncode == 0 else f"error: {result.stderr.strip()[:200]}"
    except (OSError, subprocess.TimeoutExpired) as e:
        return f"error: {e}"
