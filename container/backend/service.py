"""Service layer: project-owned runner state helpers."""

import json
from pathlib import Path


def _read_state_json(path: Path) -> dict | None:
    if not path.exists() or path.is_symlink():
        return None
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def detect_running_model() -> dict:
    """Detect selected/running model from project-owned runner state."""
    from . import config

    runner = _read_state_json(config.RUNS_DIR / "current-runner.json")
    if runner and isinstance(runner.get("model"), str):
        return {"status": "active", "family": runner["model"], "ctx": None}

    selection = _read_state_json(config.RUNS_DIR / "current-selection.json")
    selected = selection.get("model") if selection else None
    if isinstance(selected, str) and selected:
        return {"status": "selected", "family": selected, "ctx": None}
    return {"status": "inactive", "family": None, "ctx": None}
