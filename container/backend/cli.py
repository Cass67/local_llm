"""CLI wrapper: subprocess calls to model-manager scripts."""

import http.client
import importlib
import json
import os
import re
import socket
import subprocess
import time
from pathlib import Path
from urllib.parse import quote

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


def _llama_swap_model_block(model_id: str, name: str, model_path: Path, ctx: int) -> str:
    return f'''
  "{model_id}":
    name: "{name}"
    proxy: "http://127.0.0.1:${{PORT}}"
    env:
      - HIP_VISIBLE_DEVICES=0,1
      - ROCR_VISIBLE_DEVICES=0,1
    cmd: |
      ${{llama}} --port ${{PORT}}
      -m {model_path}
      -ngl 999 --split-mode layer --tensor-split 1,1
      --timeout 600 --threads-http 2 --parallel 1 --no-cont-batching
      --cache-ram 16384
      -c {ctx} --flash-attn on -ub 256 -b 4096
      --threads 16 --prio 2 --no-warmup
      --temp 0.6 --top-p 0.95 --top-k 20 --min-p 0.0
      --presence-penalty 0.5 --repeat-penalty 1.0
      --alias {model_id} --reasoning off
'''


def _add_llama_swap_model(model_id: str, repo: str, file: str, model_path: Path, ctx: int) -> None:
    path = config.LLAMA_SWAP_CONFIG
    text = path.read_text()
    name = repo.rsplit("/", 1)[-1].removesuffix("-GGUF").replace("_", " ")
    if f'  "{model_id}":' not in text:
        marker = "\nrouting:\n"
        if marker not in text:
            raise RuntimeError("llama-swap config missing routing section")
        text = text.replace(
            marker, _llama_swap_model_block(model_id, name, model_path, ctx) + marker, 1
        )
    member = f"            - {model_id}\n"
    if member not in text:
        anchor = "            - gemma-4-31b\n"
        if anchor not in text:
            raise RuntimeError("llama-swap config missing dual-gpu member anchor")
        text = text.replace(anchor, anchor + member, 1)
    path.write_text(text)


def _write_installed_metadata(model_id: str, repo: str, file: str, profile: str, ctx: int) -> None:
    config.ACCEPTED_DIR.mkdir(parents=True, exist_ok=True)
    metadata = {
        "family": model_id,
        "alias": model_id,
        "model_name": repo.rsplit("/", 1)[-1].removesuffix("-GGUF"),
        "repo": repo,
        "hf_repo": repo,
        "hf_file": file,
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


class _UnixHTTPConnection(http.client.HTTPConnection):
    def __init__(self, socket_path: Path):
        super().__init__("localhost")
        self.socket_path = socket_path

    def connect(self) -> None:
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect(str(self.socket_path))


def _restart_llama_swap() -> None:
    if not config.DOCKER_SOCKET.exists():
        raise RuntimeError("docker socket not mounted")
    conn = _UnixHTTPConnection(config.DOCKER_SOCKET)
    try:
        conn.request("POST", f"/containers/{quote('llama-swap')}/restart?t=30")
        response = conn.getresponse()
        response.read()
        if response.status not in (200, 204):
            raise RuntimeError(f"docker restart failed: HTTP {response.status}")
    finally:
        conn.close()


def run_install(repo: str, file: str, profile: str) -> dict:
    """Install model into host HF cache, register with llama-swap, and restart router."""
    os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
    try:
        huggingface_hub = importlib.import_module("huggingface_hub")
        hf_hub_download = getattr(huggingface_hub, "hf_hub_download")
    except (ImportError, AttributeError):
        return {"status": "error", "detail": "huggingface_hub is not installed"}

    ctx = 65536
    model_id = _model_id(repo, file)
    try:
        downloaded = hf_hub_download(repo_id=repo, filename=file, cache_dir=config.MODELS_CACHE_DIR)
        model_path = Path(downloaded)
        _add_llama_swap_model(model_id, repo, file, model_path, ctx)
        _write_installed_metadata(model_id, repo, file, profile, ctx)
        _restart_llama_swap()
    except Exception as exc:
        return {"status": "error", "detail": str(exc)[:500]}

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
