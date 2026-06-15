"""Service layer for model-manager TUI.

Encapsulates business logic: subprocess, ssh, model-manager.sh calls.
TUI screens call these functions; no direct subprocess in screens.
"""

from __future__ import annotations

import contextlib
import json
import subprocess  # noqa: S404 # nosec: B404
import time
from pathlib import Path
from typing import Any

from .config import (
    MODEL_DISCOVERY,
    MODEL_FIT,
    MODEL_MANAGER,
    OC_LOCAL,
    SSH_BIN,
)
from .state import get_target

REMOTE_INVENTORY_TTL_SECONDS = 20.0
_REMOTE_INVENTORY_CACHE: dict[str, tuple[float, list[dict[str, str]]]] = {}


def run_model_discovery(query: str, target: str | None) -> list[dict[str, Any]]:
    """Run model-discovery.sh and return ranked candidates."""
    if not target:
        raise ValueError("No target set; run Init first")

    host = target.split(":", 1)[1] if target.startswith("remote:") else None

    if host:
        cmd = [
            str(MODEL_DISCOVERY),
            "--host",
            host,
            "--query",
            query,
            "--limit",
            "30",
            "--json",
        ]
    else:
        cmd = [
            str(MODEL_DISCOVERY),
            "--local",
            "--query",
            query,
            "--limit",
            "30",
            "--json",
        ]

    result = subprocess.run(  # noqa: S603 # nosec: B603
        cmd,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError(f"model-discovery failed: {result.stderr.strip()[:200]}")

    scored = json.loads(result.stdout)
    ranked = scored.get("candidates", [])
    return ranked


def get_local_disk_models() -> list[tuple[str, str]]:
    """List models on local disk as (repo, path) pairs."""
    roots = [
        Path.home() / ".cache" / "huggingface" / "hub",
        Path.home() / ".cache" / "local_llm" / "models",
        Path.home() / ".cache" / "llama.cpp",
    ]
    rows: dict[str, str] = {}
    for root in roots:
        if not root.is_dir():
            continue
        for repo_dir in root.glob("models--*"):
            if not repo_dir.is_dir():
                continue
            repo = repo_dir.name.removeprefix("models--").replace("--", "/", 1)
            ggufs = sorted(repo_dir.rglob("*.gguf"))
            rows[repo] = str(ggufs[0]) if ggufs else str(repo_dir)
    return sorted(rows.items())


def get_target_inventory() -> list[dict[str, str]]:
    """Get inventory of models on target (local or remote)."""
    target = get_target() or ""
    host = target.split(":", 1)[1] if target.startswith("remote:") else None

    if host:
        try:
            return remote_inventory(host)
        except (OSError, subprocess.TimeoutExpired):
            return []

    rows: list[dict[str, str]] = []
    for repo, path in get_local_disk_models():
        rows.append({"repo": repo, "path": path, "file": Path(path).name})
    return sorted(rows, key=lambda row: row["repo"])


def remote_inventory(host: str, *, force: bool = False) -> list[dict[str, str]]:
    """Get inventory of models on remote host via SSH."""
    now = time.monotonic()
    cached = _REMOTE_INVENTORY_CACHE.get(host)
    if cached and not force and now - cached[0] < REMOTE_INVENTORY_TTL_SECONDS:
        return [dict(row) for row in cached[1]]

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
            'repo': repo,
            'path': path,
            'file': pathlib.Path(path).name,
            'disk_gb': f'{size/1_000_000_000:.1f}' if size else '-',
            'gguf': 'yes' if ggufs else 'no',
        }))
"""
    result = subprocess.run(  # noqa: S603 # nosec: B603
        [SSH_BIN, "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", host, "python3", "-"],
        input=script,
        capture_output=True,
        text=True,
        timeout=30,
    )
    rows = inventory_rows_from_stdout(result.stdout)
    _REMOTE_INVENTORY_CACHE[host] = (now, [dict(row) for row in rows])
    return rows


def inventory_rows_from_stdout(stdout: str) -> list[dict[str, str]]:
    """Parse JSONL inventory output into rows."""
    rows: dict[str, dict[str, str]] = {}
    for line in stdout.splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(item, dict) or not item.get("repo"):
            continue
        repo = str(item["repo"])
        rows[repo] = {
            "repo": repo,
            "path": str(item.get("path") or ""),
            "file": str(item.get("file") or Path(str(item.get("path") or "")).name or "?"),
            "disk_gb": str(item.get("disk_gb") or "-"),
            "gguf": str(item.get("gguf") or "no"),
        }
    return [rows[key] for key in sorted(rows)]


def get_server_status(target: str | None) -> str:
    """Check llama-server.service status on remote host."""
    if not target or not target.startswith("remote:"):
        return "local/unknown"

    host = target.split(":", 1)[1]
    try:
        result = subprocess.run(  # noqa: S603 # nosec: B603
            [
                SSH_BIN,
                "-o",
                "BatchMode=yes",
                "-o",
                "ConnectTimeout=5",
                host,
                "systemctl --user is-active llama-server.service 2>/dev/null || true",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "unreachable"
    return result.stdout.strip() or "unknown"


def detect_running_model(target: str | None) -> tuple[str, int | None]:
    """Detect which model is currently running via llama-server."""
    if not target or not target.startswith("remote:"):
        return "local/unknown", None

    host = target.split(":", 1)[1]

    # Check service active
    try:
        result = subprocess.run(  # noqa: S603 # nosec: B603
            [
                SSH_BIN,
                "-o",
                "BatchMode=yes",
                "-o",
                "ConnectTimeout=5",
                host,
                "systemctl --user is-active llama-server.service 2>/dev/null || true",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "unreachable", None

    status = result.stdout.strip()
    if status != "active":
        return "none", None

    # Read full (untruncated) cmdline via /proc to get all args
    try:
        result = subprocess.run(  # noqa: S603 # nosec: B603
            [
                SSH_BIN,
                "-o",
                "BatchMode=yes",
                "-o",
                "ConnectTimeout=5",
                host,
                "pid=$(pgrep -f llama-server | head -1); "
                '[ -n "$pid" ] && tr "\\0" "\\n" < /proc/$pid/cmdline || true',
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "active (details unknown)", None

    args = result.stdout.splitlines()
    repo: str | None = None
    hf_file: str | None = None
    tensor_split: str | None = None
    split_mode: str | None = None
    ctx_size: int | None = None
    i = 0
    while i < len(args):
        a = args[i]
        if a == "-hf" and i + 1 < len(args):
            repo = args[i + 1].split(":")[0]
        elif a.startswith("-hf="):
            repo = a.split("=", 1)[1].split(":")[0]
        elif a == "--hf-file" and i + 1 < len(args):
            hf_file = args[i + 1]
        elif a == "--tensor-split" and i + 1 < len(args):
            tensor_split = args[i + 1]
        elif a == "--split-mode" and i + 1 < len(args):
            split_mode = args[i + 1]
        elif a in ("--ctx-size", "-c") and i + 1 < len(args):
            with contextlib.suppress(ValueError):
                ctx_size = int(args[i + 1])
        i += 1

    if not repo:
        return "active (repo unknown)", ctx_size

    from .state import list_accepted

    accepted = list_accepted()

    def _config_match(data: dict, ts: str | None, sm: str | None) -> bool:
        cfg = data.get("config") or {}
        if ts is not None and str(cfg.get("tensor_split", "")) != ts:
            return False
        if sm is not None and str(cfg.get("split_mode", "")) != sm:
            return False
        return True

    # Most specific: repo + hf_file + tensor_split + split_mode
    for fam, data in accepted:
        d_repo = data.get("repo") or data.get("hf_repo") or ""
        d_file = data.get("hf_file") or ""
        if d_repo == repo and d_file == hf_file and _config_match(data, tensor_split, split_mode):
            return f"active: {fam}", ctx_size

    # repo + hf_file only
    if hf_file:
        for fam, data in accepted:
            d_repo = data.get("repo") or data.get("hf_repo") or ""
            d_file = data.get("hf_file") or ""
            if d_repo == repo and d_file == hf_file:
                return f"active: {fam}", ctx_size

    # repo only
    for fam, data in accepted:
        d_repo = data.get("repo") or data.get("hf_repo") or ""
        if d_repo == repo:
            return f"active: {fam}", ctx_size

    return f"active: {repo} (not in accepted)", ctx_size


def stop_server(target: str | None) -> str:
    """Stop llama-server.service on remote host."""
    if not target or not target.startswith("remote:"):
        raise ValueError("Stop server requires remote target")

    host = target.split(":", 1)[1]
    try:
        result = subprocess.run(  # noqa: S603 # nosec: B603
            [
                SSH_BIN,
                "-o",
                "BatchMode=yes",
                "-o",
                "ConnectTimeout=5",
                host,
                "systemctl --user stop llama-server.service",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            return "ok"
        message = (result.stderr or result.stdout or "stop failed").strip()[:200]
        return f"error: {message}"
    except (OSError, subprocess.TimeoutExpired) as e:
        return f"error: {e}"


def start_server(
    family: str,
    profile: str,
    target: str | None,
    ctx_override: str | None = None,
) -> tuple[str, str]:
    """Start model server via oc-local. Returns (status, message)."""
    if not OC_LOCAL.exists():
        return "error", "oc-local not found"

    if not target or not target.startswith("remote:"):
        return "error", "Run requires remote target"

    remote_host = target.split(":", 1)[1].strip()
    if not remote_host:
        return "error", "Invalid remote target"

    oc_cmd = ["bash", str(OC_LOCAL), family, profile, "--remote", remote_host]
    if ctx_override:
        oc_cmd.extend(["--ctx", ctx_override])

    try:
        process = subprocess.Popen(  # noqa: S603 # nosec: B603
            oc_cmd,
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
        if process.returncode != 0:
            return "error", last_stderr[:200] if last_stderr else "oc-local exited with error"
        return "ok", "Server started"
    except (subprocess.SubprocessError, OSError) as e:
        return "error", str(e)


def delete_model(repo: str, target: str | None) -> str:
    """Delete model via model-manager.sh delete. Returns status message."""
    if not target or not target.startswith("remote:"):
        raise ValueError("Delete requires remote target")

    cmd = [
        "bash",
        str(MODEL_MANAGER),
        "delete",
        repo,
        "--target",
        target,
        "--yes",
    ]

    result = subprocess.run(  # noqa: S603 # nosec: B603
        cmd,
        capture_output=True,
        text=True,
        timeout=300,
    )
    if result.returncode == 0:
        return "ok"
    message = result.stderr.strip()[:200] or "delete failed"
    return f"error: {message}"


def check_updates(dry_run: bool = True) -> str:
    """Check for recommended model updates via model-manager.sh update."""
    flags = ["update", "--dry-run"] if dry_run else ["update", "--yes"]
    result = subprocess.run(  # nosec: B603
        [str(MODEL_MANAGER)] + flags,
        capture_output=True,
        text=True,
        timeout=300,
    )
    output = (result.stdout or "").strip()
    if result.returncode != 0:
        msg = (result.stderr or "").strip().splitlines()[0]
        return f"error: {msg}"
    return output or "no updates needed"


def update_launcher(family: str) -> str:
    """Regenerate launcher for family via model-manager.sh update-launcher."""
    result = subprocess.run(  # nosec: B603
        [
            str(MODEL_MANAGER),
            "update-launcher",
            "--family",
            family,
            "--yes",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode == 0:
        return "ok"
    msg = (result.stderr or result.stdout or "").strip().splitlines()[0]
    return f"warning: {msg}"


def get_remote_downloads(target: str | None) -> list[tuple[str, str, str]]:
    """List active downloads on remote host."""
    if not target or not target.startswith("remote:"):
        return []

    host = target.split(":", 1)[1]
    try:
        result = subprocess.run(  # noqa: S603 # nosec: B603
            [
                SSH_BIN,
                "-o",
                "BatchMode=yes",
                "-o",
                "ConnectTimeout=5",
                host,
                "pgrep",
                "-af",
                "[h]f download|[h]uggingface.*download|[f]ile_download",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []

    rows: list[tuple[str, str, str]] = []
    for line in result.stdout.splitlines():
        parts = line.split()
        pid = parts[0] if parts else "?"
        repo = "?"
        file_name = ""
        if "download" in parts:
            idx = parts.index("download")
            if idx + 1 < len(parts):
                repo = parts[idx + 1]
        if "--include" in parts:
            idx = parts.index("--include")
            if idx + 1 < len(parts):
                file_name = parts[idx + 1]
        rows.append((pid, repo, file_name))
    return rows


def cancel_remote_processes(target: str | None) -> None:
    """Cancel active downloads and llama-server on remote host."""
    if not target or not target.startswith("remote:"):
        return

    host = target.split(":", 1)[1]
    try:
        subprocess.run(  # noqa: S603 # nosec: B603
            [
                SSH_BIN,
                "-o",
                "BatchMode=yes",
                "-o",
                "ConnectTimeout=5",
                host,
                "bash",
                "-lc",
                "pkill -f '[h]f download' || true; "
                "pkill -f '[h]uggingface.*download' || true; "
                "pkill -f '[f]ile_download' || true; "
                "systemctl --user stop llama-server.service >/dev/null 2>&1 || true; "
                'pkill -u "$(id -u)" -f "[l]lama-server" >/dev/null 2>&1 || true',
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        pass  # best-effort


def models_response_has_alias(stdout: str, alias: str) -> bool:
    """Check if /v1/models response includes given alias."""
    if not alias:
        return False
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        return alias in stdout
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list):
        return alias in stdout
    for item in data:
        if isinstance(item, dict) and item.get("id") == alias:
            return True
    return False


def check_remote_vram(host: str) -> float:
    """Query total VRAM on remote host in GB; fallback 20.0."""
    script = (
        "total=0; "
        "for f in /sys/class/drm/card*/device/mem_info_vram_total; do "
        '[ -r "$f" ] && total=$((total + $(cat "$f"))); '
        "done; "
        '[ "$total" -gt 0 ] && echo "$total"'
    )
    try:
        result = subprocess.run(  # noqa: S603 # nosec: B603
            [
                SSH_BIN,
                "-o",
                "BatchMode=yes",
                "-o",
                "ConnectTimeout=5",
                host,
                script,
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        try:
            return int(result.stdout.strip()) / 1_073_741_824
        except ValueError:
            return 20.0
    except (OSError, subprocess.TimeoutExpired):
        return 20.0


def select_best_quant(
    repo: str,
    host: str,
    siblings: list[dict[str, Any]],
    vram_gb: float,
) -> tuple[str, str]:
    """Run model-fit.py to choose best file/quant for given repo.

    Returns (best_file, best_quant). Raises on failure.
    """
    payload = [{"id": repo, "tags": ["gguf"], "siblings": siblings}]
    ranked = subprocess.check_output(  # nosec: B603, B607
        [
            "python3",
            str(MODEL_FIT),
            "--hardware-json",
            json.dumps({"source": f"remote:{host}", "vram_gb": vram_gb}),
            "--limit",
            "1",
            "--json",
        ],
        input=json.dumps(payload),
        text=True,
        timeout=30,
    )
    candidate = json.loads(ranked)["candidates"][0]
    hf_file = candidate.get("best_file", "")
    quant = candidate.get("best_quant", "unknown") or "unknown"
    return hf_file, quant


def get_download_size_bytes(host: str, repo_dir: Path) -> int | None:
    """Return size in bytes of a download directory on remote host.

    Uses du -sb via SSH. Returns None on error.
    """
    return get_repo_size(host, repo_dir.name)


def get_repo_size(
    host: str,
    repo_dir: str,
) -> int | None:
    """Return size in bytes of a repo directory on remote host.

    Returns None if not available.
    """
    try:
        result = subprocess.run(  # noqa: S603 # nosec: B603
            [
                SSH_BIN,
                "-o",
                "BatchMode=yes",
                "-o",
                "ConnectTimeout=5",
                host,
                "du",
                "-sb",
                f"~/.cache/huggingface/hub/{repo_dir}",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return None
        parts = result.stdout.split()
        if not parts:
            return None
        return int(parts[0])
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None


def get_remote_disk_models(host: str) -> list[dict[str, str]]:
    """List disk models on remote host with largest GGUF per repo."""
    script = r"""
import json, pathlib
root=pathlib.Path.home()/'.cache'/'huggingface'/'hub'
for repo_dir in sorted(root.glob('models--*')):
    if not repo_dir.is_dir():
        continue
    repo=repo_dir.name.removeprefix('models--').replace('--','/')
    ggufs=[]
    for p in repo_dir.rglob('*.gguf'):
        if p.name.lower().startswith('mmproj'):
            continue
        try:
            size=p.stat().st_size
        except OSError:
            size=0
        ggufs.append((size,p.name))
    if not ggufs:
        continue
    ggufs.sort(reverse=True)
    size,name=ggufs[0]
    print(json.dumps({
        'repo': repo,
        'file': name,
        'disk_gb': f'{sum(s for s, _ in ggufs)/1_000_000_000:.1f}',
    }))
"""
    try:
        result = subprocess.run(  # noqa: S603 # nosec: B603
            [
                SSH_BIN,
                "-o",
                "BatchMode=yes",
                "-o",
                "ConnectTimeout=5",
                host,
                "python3",
                "-",
            ],
            input=script,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    rows: list[dict[str, str]] = []
    for line in result.stdout.splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            rows.append({str(k): str(v) for k, v in item.items()})
    return rows


def get_delete_list(host: str) -> dict[str, tuple[str, str]]:
    """List repos on remote host for delete screen.

    Returns mapping: repo -> (size_gb, gguf_yes_no).
    """
    script = r"""
import json, pathlib, subprocess
roots=[pathlib.Path.home()/'.cache'/'huggingface'/'hub', pathlib.Path.home()/'.cache'/'local_llm'/'models', pathlib.Path.home()/'.cache'/'llama.cpp']
for root in roots:
    if not root.is_dir():
        continue
    for repo_dir in root.glob('models--*'):
        if not repo_dir.is_dir():
            continue
        repo=repo_dir.name.removeprefix('models--').replace('--','/',1)
        try:
            size=int(subprocess.check_output(['du','-sb',str(repo_dir)], text=True).split()[0])
        except (subprocess.CalledProcessError, OSError, ValueError):
            size=0
        gguf='yes' if any(p.name.lower().endswith('.gguf') and not p.name.lower().startswith('mmproj') for p in repo_dir.rglob('*.gguf')) else 'no'
        print(json.dumps({'repo': repo, 'size_gb': f'{size/1_000_000_000:.1f}' if size else '-', 'gguf': gguf}))
"""
    try:
        result = subprocess.run(  # noqa: S603 # nosec: B603
            [
                SSH_BIN,
                "-o",
                "BatchMode=yes",
                "-o",
                "ConnectTimeout=5",
                host,
                "python3",
                "-",
            ],
            input=script,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {}

    rows: dict[str, tuple[str, str]] = {}
    for line in result.stdout.splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict) and item.get("repo"):
            rows[str(item["repo"])] = (
                str(item.get("size_gb") or "-"),
                str(item.get("gguf") or "no"),
            )
    return rows
