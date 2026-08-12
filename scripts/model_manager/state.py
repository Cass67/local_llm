"""State management for model-manager.

All state lives under ~/.local/share/local_llm/runs (or $LOCAL_LLM_RUNS_DIR).
Two directories:
  - accepted/   — per-family JSON metadata
  - launchers/  — generated launcher scripts
Config (target) stored in runs/config.json, not runs/bootstrap/config.json.
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .config import (
    ACCEPTED_DIR,
    CANDIDATES_DIR,
    CANDIDATES_FILE,
    CONFIG_FILE,
    LAUNCHERS_DIR,
    RUNS_DIR,
)

SAFE_FAMILY = re.compile(r"^[A-Za-z0-9_.-]+$")
SAFE_NAME = re.compile(r"^[A-Za-z0-9_.-]+$")
# The host must not begin with "-": every remote path splits this on ":" and passes
# the tail straight into an ssh argv, so a leading dash is read by ssh as an option.
# "remote:-oProxyCommand" matched the old pattern and made ssh consume the following
# argv element -- the remote command string -- as the ProxyCommand to execute.
TARGET_RE = re.compile(r"^local$|^remote:[A-Za-z0-9_.][A-Za-z0-9_.:-]*$")


def ensure_dirs() -> None:
    """Create state directories if missing, reject symlinks."""
    for d in (RUNS_DIR, ACCEPTED_DIR, LAUNCHERS_DIR, CANDIDATES_DIR):
        if d.is_symlink():
            sys.exit(f"refuses symlinked dir: {d}")
        d.mkdir(parents=True, exist_ok=True)


def write_config(target: str) -> None:
    """Write target config. Replaces bootstrap config."""
    if not TARGET_RE.match(target):
        sys.exit(f"invalid target: {target}")
    ensure_dirs()
    if CONFIG_FILE.is_symlink():
        sys.exit(f"refuses symlinked config: {CONFIG_FILE}")
    payload = {
        "target": target,
        "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }
    CONFIG_FILE.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def read_config() -> dict[str, Any] | None:
    """Read target config. Returns None if not yet initialized."""
    # Check new location first, then legacy bootstrap location
    for path in (CONFIG_FILE, RUNS_DIR / "bootstrap" / "config.json"):
        if path.exists() and not path.is_symlink():
            try:
                return json.loads(path.read_text())
            except (json.JSONDecodeError, OSError):
                continue
    return None


def get_target() -> str | None:
    """Get current target from config, env, or None."""
    # Env override. Validated like any other target: it reaches the same ssh argv,
    # so an unvalidated env var would reopen the hole TARGET_RE closes.
    env_host = os.environ.get("OC_LOCAL_REMOTE_HOST")
    if env_host:
        target = f"remote:{env_host}"
        if not TARGET_RE.match(target):
            sys.exit(f"invalid OC_LOCAL_REMOTE_HOST: {env_host}")
        return target

    cfg = read_config()
    if cfg:
        return cfg.get("target")
    return None


def write_accepted(family: str, data: dict[str, Any]) -> Path:
    """Write accepted metadata for a family."""
    if not SAFE_FAMILY.match(family) or ".." in family:
        sys.exit(f"unsafe family name: {family}")
    ensure_dirs()
    path = ACCEPTED_DIR / f"{family}.json"
    if path.is_symlink():
        sys.exit(f"refuses symlinked accepted file: {path}")
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    return path


def read_accepted(family: str) -> dict[str, Any] | None:
    """Read accepted metadata for a family."""
    path = ACCEPTED_DIR / f"{family}.json"
    if not path.exists():
        return None
    if path.is_symlink():
        sys.exit(f"refuses symlinked accepted file: {path}")
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def list_accepted() -> list[tuple[str, dict[str, Any]]]:
    """List all accepted families with their metadata."""
    ensure_dirs()
    results = []
    for path in sorted(ACCEPTED_DIR.glob("*.json")):
        if path.name == "default.json" or path.is_symlink():
            continue
        try:
            data = json.loads(path.read_text())
            if not isinstance(data, dict) or not data.get("remote_start"):
                continue
            family = path.stem
            results.append((family, data))
        except (json.JSONDecodeError, OSError):
            continue
    return results


def has_default() -> bool:
    """Check if default.json exists."""
    return (ACCEPTED_DIR / "default.json").exists() and not (
        ACCEPTED_DIR / "default.json"
    ).is_symlink()


def delete_accepted(family: str) -> bool:
    """Delete accepted metadata for a family. Returns True if deleted."""
    if not SAFE_FAMILY.match(family):
        sys.exit(f"unsafe family name: {family}")
    path = ACCEPTED_DIR / f"{family}.json"
    if path.exists() and not path.is_symlink():
        path.unlink()
        return True
    return False


def save_candidates(candidates: list[dict[str, Any]]) -> None:
    """Save search results to candidates/latest.json."""
    ensure_dirs()
    if CANDIDATES_FILE.is_symlink():
        sys.exit(f"refuses symlinked candidates file: {CANDIDATES_FILE}")
    CANDIDATES_FILE.write_text(json.dumps(candidates, indent=2, sort_keys=True) + "\n")


def load_candidates() -> list[dict[str, Any]] | None:
    """Load saved search results. Returns None if not yet searched."""
    if not CANDIDATES_FILE.exists():
        return None
    if CANDIDATES_FILE.is_symlink():
        sys.exit(f"refuses symlinked candidates file: {CANDIDATES_FILE}")
    try:
        data = json.loads(CANDIDATES_FILE.read_text())
        if isinstance(data, list):
            return data
        return None
    except (json.JSONDecodeError, OSError):
        return None
