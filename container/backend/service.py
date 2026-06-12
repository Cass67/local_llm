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
    """Detect currently running model via llama-server process."""
    import json
    from . import config

    status = get_llama_server_status()
    if status != "active":
        return {"status": "inactive", "family": None, "ctx": None}

    try:
        result = subprocess.run(
            [
                "bash",
                "-c",
                "pid=$(pgrep -f llama-server | head -1); "
                '[ -n "$pid" ] && tr "\\0" "\\n" < /proc/$pid/cmdline || true',
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {"status": "active", "family": None, "ctx": None}

    args = result.stdout.splitlines()
    repo = None
    hf_file = None
    ctx_size = None
    i = 0
    while i < len(args):
        a = args[i]
        if a == "-hf" and i + 1 < len(args):
            repo = args[i + 1].split(":")[0]
        elif a.startswith("-hf="):
            repo = a.split("=", 1)[1].split(":")[0]
        elif a == "--hf-file" and i + 1 < len(args):
            hf_file = args[i + 1]
        elif a in ("--ctx-size", "-c") and i + 1 < len(args):
            try:
                ctx_size = int(args[i + 1])
            except ValueError:
                pass
        i += 1

    if not repo:
        return {"status": "active", "family": None, "ctx": ctx_size}

    for path in sorted(config.ACCEPTED_DIR.glob("*.json")):
        if path.name == "default.json" or path.is_symlink():
            continue
        try:
            data = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        d_repo = data.get("repo") or data.get("hf_repo") or ""
        d_file = data.get("hf_file") or ""
        if d_repo == repo and (not hf_file or d_file == hf_file):
            return {"status": "active", "family": data.get("family", path.stem), "ctx": ctx_size}

    return {"status": "active", "family": repo, "ctx": ctx_size}
