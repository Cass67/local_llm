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
