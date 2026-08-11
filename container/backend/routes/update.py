"""llama.cpp upstream update check + runner image rebuild via Docker socket."""

import asyncio
import logging
import os
import re
import subprocess  # nosec B404  # noqa: S404
import threading
import time
from pathlib import Path

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import config, regression

router = APIRouter(prefix="/api/update", tags=["update"])

GITHUB_API = "https://api.github.com/repos/ggml-org/llama.cpp"
COMMIT_LABEL = "llama.cpp.commit"
RUNNER_SRC_DIR = Path(os.environ.get("RUNNER_SRC_DIR", "/app/runner"))
BUILD_LOG = config.STATE_DIR / "runner-build.log"

_BACKENDS = ("vulkan", "rocm", "cuda")

# image id -> short sha, so we only `docker run --version` once per image build
_version_cache: dict[str, str] = {}

_build_lock = threading.Lock()
_build: dict = {"running": False, "backends": [], "current": None, "started": None, "results": {}}


def _docker(*args: str, timeout: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(  # nosec B603 B607  # noqa: S603
        ["docker", *args],  # noqa: S607
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _image_commit(image: str) -> tuple[bool, str | None]:
    """Return (image_present, short_commit_sha_or_None)."""
    try:
        result = _docker(
            "image",
            "inspect",
            "-f",
            '{{.Id}} {{index .Config.Labels "' + COMMIT_LABEL + '"}}',
            image,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False, None
    if result.returncode != 0:
        return False, None
    image_id, _, label = result.stdout.strip().partition(" ")
    if label and label != "<no value>":  # docker prints "<no value>" for a missing label
        return True, label[:12]
    if image_id in _version_cache:
        return True, _version_cache[image_id]
    # Pre-label image: llama-server --version prints "version: N (sha)"
    try:
        result = _docker("run", "--rm", image, "llama-server", "--version", timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return True, None
    match = re.search(r"\(([0-9a-f]{7,40})\)", result.stdout + result.stderr)
    if match:
        _version_cache[image_id] = match.group(1)
        return True, match.group(1)
    return True, None


def _distinct_images() -> dict[str, str]:
    return {b: config.RUNNER_IMAGES[b] for b in _BACKENDS}


@router.get("/status")
async def update_status():
    """Current llama.cpp commit per runner image vs upstream master."""
    backends = []
    current_shas: set[str] = set()
    for backend, image in _distinct_images().items():
        present, commit = _image_commit(image)
        backends.append({"backend": backend, "image": image, "present": present, "commit": commit})
        if present and commit:
            current_shas.add(commit)

    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            resp = await client.get(f"{GITHUB_API}/commits/master")
            resp.raise_for_status()
            head = resp.json()
            commits = []
            behind: dict[str, int] = {}
            for sha in current_shas:
                cmp_resp = await client.get(f"{GITHUB_API}/compare/{sha}...master")
                if cmp_resp.status_code != 200:
                    continue
                cmp = cmp_resp.json()
                behind[sha] = cmp.get("ahead_by", 0)
                if len(cmp.get("commits", [])) > len(commits):
                    commits = cmp["commits"]
            if not current_shas:
                list_resp = await client.get(f"{GITHUB_API}/commits", params={"per_page": 20})
                list_resp.raise_for_status()
                commits = list_resp.json()
        except httpx.HTTPError as e:
            raise HTTPException(502, f"GitHub unreachable: {e}") from e

    for b in backends:
        b["behind"] = behind.get(b["commit"]) if b.get("commit") else None

    return {
        "latest": {
            "sha": head["sha"],
            "message": head["commit"]["message"].splitlines()[0],
            "date": head["commit"]["committer"]["date"],
        },
        "backends": backends,
        "commits": [
            {
                "sha": c["sha"][:12],
                "message": c["commit"]["message"].splitlines()[0],
                "date": c["commit"]["committer"]["date"],
                "author": (c["commit"]["author"] or {}).get("name", ""),
            }
            for c in list(reversed(commits))[:50]  # newest first
        ],
    }


def _run_builds(targets: list[tuple[str, str]], ref: str) -> None:
    with open(BUILD_LOG, "w") as log:
        for backend, image in targets:
            _build["current"] = backend
            log.write(f"\n=== Building {image} @ {ref[:12]} ===\n")
            log.flush()
            proc = subprocess.Popen(  # nosec B603 B607  # noqa: S603
                [  # noqa: S607
                    "docker",
                    "build",
                    "--network",
                    "host",
                    "--build-arg",
                    f"LLAMA_CPP_REF={ref}",
                    "--label",
                    f"{COMMIT_LABEL}={ref}",
                    "-t",
                    image,
                    str(RUNNER_SRC_DIR / backend),
                ],
                stdout=log,
                stderr=subprocess.STDOUT,
            )
            _build["results"][backend] = proc.wait()
            _version_cache.clear()
    _build["current"] = None
    _build["running"] = False

    # A rebuild is the moment upstream performance changes; measure it now, while
    # we know which commit caused it, rather than noticing weeks later.
    if _build["results"] and all(code == 0 for code in _build["results"].values()):
        _build["current"] = "regression guard"
        _build["running"] = True
        try:
            _build["regression"] = regression.run_guard(ref)
        except Exception as exc:  # noqa: BLE001
            logging.warning("regression guard failed after build: %s", exc)
        finally:
            _build["current"] = None
            _build["running"] = False


class BuildRequest(BaseModel):
    backends: list[str]


@router.post("/build")
async def start_build(req: BuildRequest):
    """Rebuild selected runner images against current upstream master."""
    targets = []
    for backend in req.backends:
        if backend not in _BACKENDS:
            raise HTTPException(400, f"unknown backend '{backend}'")
        if not (RUNNER_SRC_DIR / backend / "Dockerfile").exists():
            raise HTTPException(500, f"runner sources for '{backend}' not found in image")
        targets.append((backend, config.RUNNER_IMAGES[backend]))
    if not targets:
        raise HTTPException(400, "no backends given")

    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            resp = await client.get(f"{GITHUB_API}/commits/master")
            resp.raise_for_status()
            ref = resp.json()["sha"]
        except httpx.HTTPError as e:
            raise HTTPException(502, f"GitHub unreachable: {e}") from e

    with _build_lock:
        if _build["running"]:
            raise HTTPException(409, "a build is already running")
        _build.update(
            running=True,
            backends=[b for b, _ in targets],
            current=None,
            started=time.time(),
            results={},
        )
    threading.Thread(target=_run_builds, args=(targets, ref), daemon=True).start()
    return {"status": "started", "ref": ref, "backends": _build["backends"]}


@router.get("/build/status")
async def build_status():
    log_tail = ""
    if BUILD_LOG.exists():
        try:
            lines = BUILD_LOG.read_text(errors="replace").splitlines()
            log_tail = "\n".join(lines[-40:])
        except OSError:
            pass
    return {
        "running": _build["running"],
        "backends": _build["backends"],
        "current": _build["current"],
        "started": _build["started"],
        "results": _build["results"],
        "log_tail": log_tail,
        "regression": _build.get("regression"),
    }


@router.get("/regression")
async def regression_report():
    """Most recent post-rebuild throughput comparison, plus the known-good baselines."""
    return {"report": regression.last_report(), "baselines": regression.load_baselines()}


@router.post("/regression/run")
async def run_regression_guard(commit: str = ""):
    """Measure every running cluster against its baseline without rebuilding."""
    if _build["running"]:
        raise HTTPException(409, "a build is already running")
    return await asyncio.to_thread(regression.run_guard, commit)


@router.post("/regression/accept")
async def accept_regression_baseline():
    """Bless the latest measurement as the new known-good."""
    return regression.accept_current_as_baseline()
