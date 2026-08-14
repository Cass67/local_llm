import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

STATE_DIR = Path(os.environ.get("LOCAL_LLM_STATE_DIR", "/state"))
LLAMA_CPP_DIR = Path(os.environ.get("LLAMA_CPP_DIR", "/llama.cpp"))
MODELS_CACHE_DIR = Path(os.environ.get("MODELS_CACHE_DIR", "/models"))
HOST_MODELS_CACHE_DIR = Path(os.environ.get("HOST_MODELS_CACHE_DIR", str(MODELS_CACHE_DIR)))
DOCKER_SOCKET = Path(os.environ.get("DOCKER_SOCKET", "/var/run/docker.sock"))
LLAMA_SERVER_PORT = int(os.environ.get("LLAMA_SERVER_PORT", "8080"))
RUNNER_URL = os.environ.get("RUNNER_URL", f"http://127.0.0.1:{LLAMA_SERVER_PORT}/v1").rstrip("/")
RUNNER_IMAGES = {
    "vulkan": os.environ.get("RUNNER_IMAGE_VULKAN", "local-llm-runner-vulkan:latest"),
    "mixed_vulkan": os.environ.get("RUNNER_IMAGE_VULKAN", "local-llm-runner-vulkan:latest"),
    "rocm": os.environ.get("RUNNER_IMAGE_ROCM", "local-llm-runner-rocm:latest"),
    "rocmfp4": os.environ.get("RUNNER_IMAGE_ROCMFP4", "local-llm-runner-rocmfp4:latest"),
    "cuda": os.environ.get("RUNNER_IMAGE_CUDA", "local-llm-runner-cuda:latest"),
}


def runner_image_for_backend(backend: str) -> str:
    return RUNNER_IMAGES.get(backend, RUNNER_IMAGES["rocm"])


DISABLE_THINKING_BY_DEFAULT = os.environ.get(
    "LOCAL_LLM_DISABLE_THINKING_BY_DEFAULT", "false"
).lower() in {"1", "true", "yes", "on"}
VERSION = "0.1.0"

RUNS_DIR = STATE_DIR / "runs"
ACCEPTED_DIR = RUNS_DIR / "accepted"
SCRIPTS_DIR = Path(os.environ.get("SCRIPTS_DIR", "/scripts"))
LLAMA_SWAP_CONFIG = Path(os.environ.get("LLAMA_SWAP_CONFIG", "/home/cass/llama-swap/config.yaml"))
ROUTER_CONFIG = Path(os.environ.get("ROUTER_CONFIG", str(STATE_DIR / "router_rules.json")))
ROUTER_PORT = int(os.environ.get("ROUTER_PORT", "3200"))
PROFILES_CONFIG = Path(os.environ.get("PROFILES_CONFIG", str(STATE_DIR / "profiles.json")))
PROFILE_SNAPSHOTS_DIR = STATE_DIR / "profile-snapshots"
PROFILE_SNAPSHOTS_KEEP = int(os.environ.get("PROFILE_SNAPSHOTS_KEEP", "100"))


def snapshot_profiles(label: str = "") -> str | None:
    """Copy the current profiles.json aside before it is overwritten.

    Returns the snapshot id, or None if there was nothing to snapshot.
    """
    if not PROFILES_CONFIG.exists():
        return None
    raw = PROFILES_CONFIG.read_text()
    slug = re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")[:40]
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    snap_id = f"{stamp}_{slug}" if slug else stamp
    PROFILE_SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    (PROFILE_SNAPSHOTS_DIR / f"{snap_id}.json").write_text(raw)
    for stale in sorted(PROFILE_SNAPSHOTS_DIR.glob("*.json"))[:-PROFILE_SNAPSHOTS_KEEP]:
        stale.unlink(missing_ok=True)
    return snap_id


def save_profiles(data: dict[str, Any], label: str = "") -> None:
    """Write profiles.json, snapshotting the previous contents first."""
    snapshot_profiles(label)
    PROFILES_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    PROFILES_CONFIG.write_text(json.dumps(data, indent=2))
