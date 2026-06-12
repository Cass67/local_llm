"""CLI wrapper: subprocess calls to model-manager scripts."""
import json
import subprocess
import time
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
        cmd, capture_output=True, text=True, timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip()[:300] or "discovery failed")

    data = json.loads(result.stdout)
    return data.get("candidates", [])


def run_delete(repo: str, target: str) -> str:
    """Delete model via model-manager.sh delete."""
    cmd = ["bash", str(MODEL_MANAGER), "delete", repo, "--target", target, "--yes"]
    result = subprocess.run(  # noqa: S603
        cmd, capture_output=True, text=True, timeout=300,
    )
    if result.returncode == 0:
        return "ok"
    return f"error: {result.stderr.strip()[:200]}"


def run_update_launcher(family: str) -> str:
    """Regenerate launcher for family."""
    cmd = [str(MODEL_MANAGER), "update-launcher", "--family", family, "--yes"]
    result = subprocess.run(  # noqa: S603
        cmd, capture_output=True, text=True, timeout=30,
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
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
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
            capture_output=True, text=True, timeout=30,
        )
        return "ok" if result.returncode == 0 else f"error: {result.stderr.strip()[:200]}"
    except (OSError, subprocess.TimeoutExpired) as e:
        return f"error: {e}"
