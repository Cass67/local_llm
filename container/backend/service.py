"""Service layer: systemd interaction for llama-server on host."""

import subprocess


def restart_llama_server() -> bool:
    """Restart llama-server via host systemd --user."""
    try:
        result = subprocess.run(
            ["systemctl", "--user", "restart", "llama-server.service"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return False


def get_llama_server_status() -> str:
    """Get llama-server service status."""
    try:
        result = subprocess.run(
            ["systemctl", "--user", "is-active", "llama-server.service"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return "unknown"


def _read_state_json(path):
    import json

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
