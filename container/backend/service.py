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


def detect_running_model() -> dict:
    """Detect selected/running model via llama-swap."""
    import json
    import urllib.error
    import urllib.request
    from . import config

    selected = None
    selection_file = config.RUNS_DIR / "current-selection.json"
    if selection_file.exists() and not selection_file.is_symlink():
        try:
            selection = json.loads(selection_file.read_text())
            if isinstance(selection, dict):
                selected = selection.get("model")
        except (OSError, json.JSONDecodeError):
            selected = None

    running_ids: list[str] = []
    try:
        with urllib.request.urlopen(f"{config.LLAMA_SWAP_URL}/running", timeout=5) as response:
            body = json.loads(response.read().decode("utf-8"))
        running = body.get("running") if isinstance(body, dict) else []
        if isinstance(running, list):
            for item in running:
                if isinstance(item, str):
                    running_ids.append(item)
                elif isinstance(item, dict) and item.get("id"):
                    running_ids.append(str(item["id"]))
                elif isinstance(item, dict) and item.get("model"):
                    running_ids.append(str(item["model"]))
    except (OSError, urllib.error.URLError, json.JSONDecodeError):
        pass

    family = selected or (running_ids[0] if running_ids else None)
    if family and family in running_ids:
        return {"status": "active", "family": family, "ctx": None}
    if family:
        return {"status": "selected", "family": family, "ctx": None}
    return {"status": "inactive", "family": None, "ctx": None}
