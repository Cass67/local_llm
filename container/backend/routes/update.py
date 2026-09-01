"""llama.cpp upstream update check + runner image rebuild via Docker socket."""

import asyncio
import json
import logging
import os
import re
import subprocess  # nosec B404  # noqa: S404
import threading
import time
from collections.abc import Collection
from pathlib import Path

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import config, regression, runtime

router = APIRouter(prefix="/api/update", tags=["update"])

GITHUB_REPOS = "https://api.github.com/repos"
GITHUB_API = f"{GITHUB_REPOS}/ggml-org/llama.cpp"
# Anonymous GitHub allows 60 requests an hour per IP, and one "check for updates"
# spends a dozen (a page of master history, a tag walk for Langfuse). A token
# raises that to 5000, and deep history pages 504 without one; the cache keeps a
# refresh cheap either way.
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_CACHE_TTL = 600.0
COMMIT_LABEL = "llama.cpp.commit"
RUNNER_SRC_DIR = Path(os.environ.get("RUNNER_SRC_DIR", "/app/runner"))
BUILD_LOG_PREFIX = "build-"

# Only backends built from ggml-org/llama.cpp belong here: the rebuild passes
# --build-arg LLAMA_CPP_REF=<upstream sha>, which would silently build upstream
# instead of the fork for rocmqwen4exp2 / rocmfork / rocmdflash2.
_BACKENDS = ("vulkan", "rocm", "cuda", "rocmmain")

_gh_cache: dict[str, tuple[float, httpx.Response]] = {}


class GitHub:
    """GitHub client with auth and a short response cache, to stay under the quota."""

    def __init__(self, timeout: float = 20.0):
        self._timeout = timeout
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "GitHub":
        headers = {"Accept": "application/vnd.github+json"}
        if GITHUB_TOKEN:
            headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"
        self._client = httpx.AsyncClient(timeout=self._timeout, headers=headers)
        await self._client.__aenter__()
        return self

    async def __aexit__(self, *exc) -> bool:
        if self._client:
            await self._client.__aexit__(*exc)
        return False

    async def get(self, url: str, **kw) -> httpx.Response:
        key = f"{url}?{sorted((kw.get('params') or {}).items())}"
        hit = _gh_cache.get(key)
        if hit and hit[0] > time.monotonic():
            return hit[1]
        resp = await self._client.get(url, **kw)  # ty: ignore[possibly-unbound-attribute]
        if resp.status_code in (403, 429) and resp.headers.get("x-ratelimit-remaining") == "0":
            raise HTTPException(429, _rate_limit_message(resp))
        if resp.status_code == 200:
            _gh_cache[key] = (time.monotonic() + GITHUB_CACHE_TTL, resp)
        return resp


def _rate_limit_message(resp: httpx.Response) -> str:
    reset = resp.headers.get("x-ratelimit-reset")
    when = ""
    if reset and reset.isdigit():
        when = f" until {time.strftime('%H:%M', time.localtime(int(reset)))}"
    if GITHUB_TOKEN:
        return f"GitHub rate limit exhausted{when}."
    return (
        f"GitHub rate limit exhausted{when} (60/hour without a token). "
        "Set GITHUB_TOKEN in .env and redeploy to raise it to 5000/hour."
    )


# The coding-agent image (pi + opencode) is version-pinned by build arg, so a
# plain `docker compose build` is a cache hit and never picks up new releases.
AGENTS_SRC_DIR = Path(os.environ.get("AGENTS_SRC_DIR", "/app/agents"))
AGENTS_IMAGE = os.environ.get("AGENTS_IMAGE", "local-llm-agents:latest")
# id -> (npm package, Dockerfile build arg, container using it, platform package)
# opencode ships its binary in per-platform packages that are published a few
# minutes after the release itself, so `latest` is briefly uninstallable.
AGENT_PACKAGES = {
    "pi": ("@earendil-works/pi-coding-agent", "PI_VERSION", "local-llm-pi-web", None),
    "opencode": ("opencode-ai", "OPENCODE_VERSION", "local-llm-opencode", "opencode-linux-x64"),
}
NPM_REGISTRY = "https://registry.npmjs.org"

# Abbreviated packument: the full one for opencode is megabytes of changelog.
NPM_ABBREVIATED = {"Accept": "application/vnd.npm.install-v1+json"}

# The rest of the stack: containers we run from someone else's release instead of
# building from llama.cpp. The chat UI is a pulled image tracking a branch; Langfuse
# is built here because the /traces base path is baked in at build time.
SERVICES: dict[str, dict] = {
    "chat": {
        "name": "Open WebUI (chat)",
        "kind": "pull",
        "container": "open-webui",
        "image": "ghcr.io/open-webui/open-webui:main",
        "repo": "open-webui/open-webui",
        "branch": "main",
    },
    "langfuse": {
        "name": "Langfuse (traces)",
        "kind": "git-build",
        "container": "local-llm-langfuse",
        "image": "local-llm-langfuse:traces",
        "repo": "langfuse/langfuse",
        # Pinned to the v2 line: v3+ needs ClickHouse, Redis and S3, none of which
        # this stack deploys, so a "latest" build would come up dead.
        "series": "v2.",
        "dockerfile": "web/Dockerfile",
        "build_args": {"NEXT_PUBLIC_BASE_PATH": "/traces"},
        "version_label": "langfuse.version",
    },
}

# image id -> short sha, so we only `docker run --version` once per image build
_version_cache: dict[str, str] = {}

# One job per updatable thing, running concurrently: a Langfuse rebuild takes
# minutes and must not block an opencode bump. The three runners stay a single
# job -- they build the same llama.cpp source, and serialising them keeps the
# machine responsive while it compiles.
_jobs_lock = threading.Lock()
_jobs: dict[str, dict] = {}


def _job_log(job_id: str) -> Path:
    return config.STATE_DIR / f"{BUILD_LOG_PREFIX}{job_id}.log"


def _claim_job(job_id: str, targets: list[str]) -> dict:
    """Reserve the job slot, or 409 if that same job is already building."""
    with _jobs_lock:
        if _jobs.get(job_id, {}).get("running"):
            raise HTTPException(409, f"'{job_id}' is already building")
        job = {
            "id": job_id,
            "running": True,
            "targets": targets,
            "current": None,
            "started": time.time(),
            "results": {},
        }
        _jobs[job_id] = job
        return job


def _finish(job: dict) -> None:
    job["current"] = None
    job["running"] = False


def _others_running(job_id: str) -> bool:
    return any(j["running"] for jid, j in _jobs.items() if jid != job_id)


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
    # Pre-label image. Older builds print "version: N (sha)"; since roughly b10700 the
    # format is "version: 0.3.0-dev (build 1, commit 3466812)", which the bare-parens
    # pattern does not match, so try the commit form too before giving up.
    try:
        result = _docker("run", "--rm", image, "llama-server", "--version", timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return True, None
    out = result.stdout + result.stderr
    match = re.search(r"\(([0-9a-f]{7,40})\)", out) or re.search(r"commit ([0-9a-f]{7,40})", out)
    if match:
        _version_cache[image_id] = match.group(1)
        return True, match.group(1)
    return True, None


def _distinct_images() -> dict[str, str]:
    return {b: config.RUNNER_IMAGES[b] for b in _BACKENDS}


# GitHub's /compare endpoint cannot keep up with llama.cpp: past roughly a day of
# master it times out (504), then serves the cached failure as a 404 -- with or
# without a token. Walking the commit list instead is one request per 100 commits
# and never fails that way.
HISTORY_PAGES = 5


async def _branch_history(
    client, repo: str, branch: str, until: Collection[str] = (), pages: int = HISTORY_PAGES
) -> list[dict]:
    """Newest-first commits on a branch, stopping once every sha in `until` is in hand."""
    history: list[dict] = []
    for page in range(1, pages + 1):
        resp = await client.get(
            f"{GITHUB_REPOS}/{repo}/commits",
            params={"sha": branch, "per_page": 100, "page": page},
        )
        if resp.status_code != 200:
            break
        batch = resp.json()
        history += batch
        if len(batch) < 100:
            break
        if until and all(_behind(history, sha) is not None for sha in until):
            break
    return history


def _behind(history: list[dict], sha: str) -> int | None:
    """How many commits `history` holds ahead of `sha`, or None if it is out of range."""
    for i, commit in enumerate(history):
        if commit["sha"].startswith(sha):  # image labels carry a truncated sha
            return i
    return None


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

    async with GitHub(timeout=15.0) as client:
        try:
            history = await _branch_history(
                client, "ggml-org/llama.cpp", "master", until=current_shas
            )
        except httpx.HTTPError as e:
            raise HTTPException(502, f"GitHub unreachable: {e}") from e
    if not history:
        raise HTTPException(502, "GitHub returned no commits for llama.cpp master")

    head = history[0]
    for b in backends:
        b["behind"] = _behind(history, b["commit"]) if b.get("commit") else None

    depth = max((b["behind"] or 0 for b in backends), default=0)
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
            for c in history[: min(max(depth, 20), 50)]  # newest first
        ],
    }


@router.get("/commit/{sha}")
async def commit_detail(sha: str):
    """Full commit, touched files, and the PR it came from (body + discussion)."""
    if not re.fullmatch(r"[0-9a-fA-F]{7,40}", sha):
        raise HTTPException(400, "not a commit sha")

    async with GitHub(timeout=20.0) as client:

        async def get(url: str, **kw):
            resp = await client.get(url, **kw)
            resp.raise_for_status()
            return resp.json()

        try:
            commit = await get(f"{GITHUB_API}/commits/{sha}")
            pulls = await get(f"{GITHUB_API}/commits/{sha}/pulls")
            pull = None
            if pulls:
                pr = pulls[0]
                comments = await get(
                    f"{GITHUB_API}/issues/{pr['number']}/comments", params={"per_page": 30}
                )
                reviews = await get(
                    f"{GITHUB_API}/pulls/{pr['number']}/comments", params={"per_page": 30}
                )
                pull = {
                    "number": pr["number"],
                    "title": pr["title"],
                    "body": pr.get("body") or "",
                    "url": pr["html_url"],
                    "state": pr["state"],
                    "merged_at": pr.get("merged_at"),
                    "user": (pr.get("user") or {}).get("login", ""),
                    "comments": [
                        {
                            "user": (c.get("user") or {}).get("login", ""),
                            "body": c.get("body") or "",
                            "date": c["created_at"],
                            "path": c.get("path"),
                        }
                        for c in sorted(comments + reviews, key=lambda c: c["created_at"])
                    ],
                }
        except httpx.HTTPError as e:
            raise HTTPException(502, f"GitHub unreachable: {e}") from e

    message = commit["commit"]["message"]
    return {
        "sha": commit["sha"],
        "url": commit["html_url"],
        "subject": message.splitlines()[0],
        "body": "\n".join(message.splitlines()[1:]).strip(),
        "author": (commit["commit"]["author"] or {}).get("name", ""),
        "date": commit["commit"]["committer"]["date"],
        "stats": commit.get("stats", {}),
        "files": [
            {
                "filename": f["filename"],
                "status": f["status"],
                "additions": f["additions"],
                "deletions": f["deletions"],
            }
            for f in commit.get("files", [])[:100]
        ],
        "pull": pull,
    }


def _parse_npm_versions(payload: str) -> dict[str, str]:
    """package -> version, from `npm ls -g --depth=0 --json`."""
    try:
        deps = json.loads(payload).get("dependencies") or {}
    except (json.JSONDecodeError, AttributeError):
        return {}
    return {
        name: info["version"]
        for name, info in deps.items()
        if isinstance(info, dict) and info.get("version")
    }


# image id -> installed npm versions, so we shell into the image once per build
_agent_version_cache: dict[str, dict[str, str]] = {}


def _installed_agent_versions() -> tuple[bool, dict[str, str]]:
    try:
        result = _docker("image", "inspect", "-f", "{{.Id}}", AGENTS_IMAGE)
    except (OSError, subprocess.TimeoutExpired):
        return False, {}
    if result.returncode != 0:
        return False, {}
    image_id = result.stdout.strip()
    if image_id not in _agent_version_cache:
        try:
            listing = _docker(
                "run", "--rm", AGENTS_IMAGE, "npm", "ls", "-g", "--depth=0", "--json", timeout=120
            )
        except (OSError, subprocess.TimeoutExpired):
            return True, {}
        _agent_version_cache[image_id] = _parse_npm_versions(listing.stdout)
    return True, _agent_version_cache[image_id]


async def _npm_latest(client: httpx.AsyncClient, package: str) -> str | None:
    resp = await client.get(f"{NPM_REGISTRY}/{package}/latest")
    if resp.status_code != 200:
        return None
    return resp.json().get("version")


async def _installable_version(
    client: httpx.AsyncClient, package: str, platform_package: str | None
) -> str | None:
    """Newest release whose platform package is also published — see AGENT_PACKAGES."""
    latest = await _npm_latest(client, package)
    if not latest or not platform_package:
        return latest

    async def published(version: str) -> bool:
        resp = await client.get(f"{NPM_REGISTRY}/{platform_package}/{version}")
        return resp.status_code == 200

    if await published(latest):
        return latest
    doc = await client.get(f"{NPM_REGISTRY}/{package}", headers=NPM_ABBREVIATED)
    if doc.status_code != 200:
        return None
    # Registry order is publication order. Prereleases (0.0.0-dev-*) are published
    # continuously and never carry platform packages, so they are not candidates.
    # Walk back a few stable releases, no further: a longer gap means something
    # other than a publish race is wrong.
    stable = [v for v in doc.json().get("versions", {}) if "-" not in v and v != latest]
    for version in stable[-5:][::-1]:
        if await published(version):
            return version
    return None


@router.get("/agents")
async def agents_status():
    """Installed vs latest pi/opencode in the coding-agent image."""
    present, installed = _installed_agent_versions()
    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            latest = {
                agent_id: await _installable_version(client, package, platform)
                for agent_id, (package, _, _, platform) in AGENT_PACKAGES.items()
            }
        except httpx.HTTPError as e:
            raise HTTPException(502, f"npm registry unreachable: {e}") from e

    return {
        "image": AGENTS_IMAGE,
        "present": present,
        "packages": [
            {
                "id": agent_id,
                "package": package,
                "container": container,
                "current": installed.get(package),
                "latest": latest[agent_id],
                "outdated": bool(
                    latest[agent_id]
                    and installed.get(package)
                    and latest[agent_id] != installed[package]
                ),
            }
            for agent_id, (package, _, container, _p) in AGENT_PACKAGES.items()
        ],
    }


def _recreate_container(name: str, image: str | None = None) -> None:
    """Re-create a container from its own config so it picks up the rebuilt image."""

    def api(method: str, path: str, body: str | None = None) -> dict:
        return runtime.docker_api(method, path, body, config.DOCKER_SOCKET)

    info = api("GET", f"/containers/{name}/json")
    if not info:
        return  # agent container is not deployed on this host
    cfg = info["Config"]
    payload = {
        key: cfg[key]
        for key in ("Image", "Cmd", "Entrypoint", "Env", "User", "WorkingDir", "Labels", "Tty")
        if key in cfg
    }
    if image:
        payload["Image"] = image  # the deployed container may still name an older tag
    payload["HostConfig"] = info["HostConfig"]
    api("POST", f"/containers/{name}/stop?t=10")
    api("DELETE", f"/containers/{name}?force=true")
    api("POST", f"/containers/create?name={name}", json.dumps(payload))
    api("POST", f"/containers/{name}/start")


def _run_agents_build(job: dict, versions: dict[str, str]) -> None:
    build_args = []
    for agent_id, version in versions.items():
        build_args += ["--build-arg", f"{AGENT_PACKAGES[agent_id][1]}={version}"]
    with open(_job_log(job["id"]), "w") as log:
        job["current"] = "agents"
        pinned = ", ".join(f"{a} {v}" for a, v in versions.items())
        log.write(f"\n=== Building {AGENTS_IMAGE} ({pinned}) ===\n")
        log.flush()
        proc = subprocess.Popen(  # nosec B603 B607  # noqa: S603
            [  # noqa: S607
                "docker",
                "build",
                "--network",
                "host",
                "--pull",
                *build_args,
                "-t",
                AGENTS_IMAGE,
                str(AGENTS_SRC_DIR),
            ],
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        code = proc.wait()
        job["results"]["agents"] = code
        _agent_version_cache.clear()
        # The image tag is unchanged, so the running containers keep the old one
        # until they are re-created -- unlike runners, nothing else relaunches them.
        if code == 0:
            for agent_id in versions:
                name = AGENT_PACKAGES[agent_id][2]
                try:
                    _recreate_container(name)
                    log.write(f"recreated {name}\n")
                except (RuntimeError, OSError) as exc:
                    log.write(f"failed to recreate {name}: {exc}\n")
                    job["results"]["agents"] = 1
                log.flush()
    _finish(job)


@router.post("/agents/build")
async def start_agents_build():
    """Rebuild the coding-agent image at the latest pi/opencode releases and restart both."""
    if not (AGENTS_SRC_DIR / "Dockerfile").exists():
        raise HTTPException(500, f"agent sources not found in image at {AGENTS_SRC_DIR}")

    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            versions = {}
            for agent_id, (package, _, _, platform) in AGENT_PACKAGES.items():
                version = await _installable_version(client, package, platform)
                if not version:
                    raise HTTPException(502, f"no installable version for {package}")
                versions[agent_id] = version
        except httpx.HTTPError as e:
            raise HTTPException(502, f"npm registry unreachable: {e}") from e

    job = _claim_job("agents", ["agents"])
    threading.Thread(target=_run_agents_build, args=(job, versions), daemon=True).start()
    return {"status": "started", "versions": versions}


def _image_meta(image: str) -> tuple[bool, dict[str, str], list[str]]:
    """(present, labels, repo_tags) for a local image."""
    try:
        result = _docker(
            "image", "inspect", "-f", "{{json .Config.Labels}}|{{json .RepoTags}}", image
        )
    except (OSError, subprocess.TimeoutExpired):
        return False, {}, []
    if result.returncode != 0:
        return False, {}, []
    labels_json, _, tags_json = result.stdout.strip().partition("|")
    try:
        labels = json.loads(labels_json) or {}
        tags = json.loads(tags_json) or []
    except json.JSONDecodeError:
        return True, {}, []
    return True, labels, tags


def _version_key(tag: str) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", tag))


async def _latest_tag(client: httpx.AsyncClient, repo: str, series: str) -> str | None:
    """Newest stable release tag in a pinned major series (e.g. 'v2.')."""
    for page in range(1, 6):
        resp = await client.get(
            f"{GITHUB_REPOS}/{repo}/tags", params={"per_page": 100, "page": page}
        )
        if resp.status_code != 200:
            return None
        names = [t["name"] for t in resp.json()]
        if not names:
            return None
        matching = [n for n in names if n.startswith(series) and "-" not in n]
        if matching:
            return max(matching, key=_version_key)
    return None


async def _service_row(client: httpx.AsyncClient, service_id: str, svc: dict) -> dict:
    present, labels, tags = _image_meta(svc["image"])
    row = {
        "id": service_id,
        "name": svc["name"],
        "kind": svc["kind"],
        "container": svc["container"],
        "image": svc["image"],
        "present": present,
        "current": None,
        "latest": None,
        "behind": None,
        "outdated": False,
        "note": None,
    }

    if svc["kind"] == "pull":
        # Branch-tracking tag: the image's own version label just says "main", so
        # the upstream commit it was built from is the only real version we have.
        revision = labels.get("org.opencontainers.image.revision")
        history = await _branch_history(
            client, svc["repo"], svc["branch"], until=[revision] if revision else ()
        )
        row["latest"] = history[0]["sha"][:12] if history else None
        row["current"] = revision[:12] if revision else None
        if revision and history:
            row["behind"] = _behind(history, revision)
            row["outdated"] = bool(row["behind"])
        return row

    version = labels.get(svc["version_label"])
    if not version:
        # Pre-label image, or the compose-pinned tag it was first deployed under.
        match = re.search(r"\d+\.\d+\.\d+", " ".join(tags))
        version = match.group(0) if match else None
    latest = await _latest_tag(client, svc["repo"], svc["series"])
    row["current"] = version
    row["latest"] = latest.lstrip("v") if latest else None
    row["outdated"] = bool(version and row["latest"] and version != row["latest"])
    row["note"] = f"pinned to the {svc['series'].rstrip('.')} line"
    return row


@router.get("/services")
async def services_status():
    """Installed vs upstream for the chat and tracing containers."""
    async with GitHub(timeout=20.0) as client:
        try:
            rows = [await _service_row(client, sid, svc) for sid, svc in SERVICES.items()]
        except httpx.HTTPError as e:
            raise HTTPException(502, f"upstream unreachable: {e}") from e
    return {"services": rows}


def _run_service_update(job: dict, svc: dict, ref: str | None) -> None:
    service_id = job["id"]
    with open(_job_log(service_id), "w") as log:
        job["current"] = service_id
        if svc["kind"] == "pull":
            log.write(f"\n=== Pulling {svc['image']} ===\n")
            cmd = ["docker", "pull", svc["image"]]
        else:
            log.write(f"\n=== Building {svc['image']} @ {ref} ===\n")
            args = []
            for key, value in svc["build_args"].items():
                args += ["--build-arg", f"{key}={value}"]
            cmd = [
                "docker",
                "build",
                "--network",
                "host",
                "-f",
                svc["dockerfile"],
                *args,
                "--label",
                f"{svc['version_label']}={(ref or '').lstrip('v')}",
                "-t",
                svc["image"],
                f"https://github.com/{svc['repo']}.git#{ref}",
            ]
        log.flush()
        proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT)  # nosec B603  # noqa: S603
        code = proc.wait()
        job["results"][service_id] = code
        if code == 0:
            try:
                _recreate_container(svc["container"], svc["image"])
                log.write(f"recreated {svc['container']}\n")
            except (RuntimeError, OSError) as exc:
                log.write(f"failed to recreate {svc['container']}: {exc}\n")
                job["results"][service_id] = 1
            log.flush()
    _finish(job)


@router.post("/services/{service_id}/build")
async def start_service_update(service_id: str):
    """Pull or rebuild one supporting container, then re-create it at the new image."""
    svc = SERVICES.get(service_id)
    if not svc:
        raise HTTPException(404, f"unknown service '{service_id}'")

    ref = None
    if svc["kind"] == "git-build":
        async with GitHub(timeout=20.0) as client:
            try:
                ref = await _latest_tag(client, svc["repo"], svc["series"])
            except httpx.HTTPError as e:
                raise HTTPException(502, f"GitHub unreachable: {e}") from e
        if not ref:
            raise HTTPException(502, f"no {svc['series']}x release found for {svc['repo']}")

    job = _claim_job(service_id, [service_id])
    threading.Thread(target=_run_service_update, args=(job, svc, ref), daemon=True).start()
    return {"status": "started", "ref": ref}


def _run_builds(job: dict, targets: list[tuple[str, str]], ref: str) -> None:
    with open(_job_log(job["id"]), "w") as log:
        for backend, image in targets:
            job["current"] = backend
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
            job["results"][backend] = proc.wait()
            _version_cache.clear()

    # A rebuild is the moment upstream performance changes; measure it now, while
    # we know which commit caused it, rather than noticing weeks later.
    if job["results"] and all(code == 0 for code in job["results"].values()):
        job["current"] = "regression guard"
        # Another job compiling in the background would eat the CPU this measures
        # against, so wait it out rather than blame upstream for the slowdown.
        while _others_running(job["id"]):
            time.sleep(5)
        try:
            job["regression"] = regression.run_guard(ref)
        except Exception as exc:  # noqa: BLE001
            logging.warning("regression guard failed after build: %s", exc)
    _finish(job)


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

    async with GitHub(timeout=15.0) as client:
        try:
            resp = await client.get(f"{GITHUB_API}/commits/master")
            resp.raise_for_status()
            ref = resp.json()["sha"]
        except httpx.HTTPError as e:
            raise HTTPException(502, f"GitHub unreachable: {e}") from e

    job = _claim_job("runners", [b for b, _ in targets])
    threading.Thread(target=_run_builds, args=(job, targets, ref), daemon=True).start()
    return {"status": "started", "ref": ref, "backends": job["targets"]}


def _log_tail(job_id: str) -> str:
    path = _job_log(job_id)
    if not path.exists():
        return ""
    try:
        return "\n".join(path.read_text(errors="replace").splitlines()[-40:])
    except OSError:
        return ""


@router.get("/build/status")
async def build_status():
    """Every build job, running or last-finished. Jobs are independent."""
    jobs = [
        {**job, "log_tail": _log_tail(job["id"])}
        for job in sorted(_jobs.values(), key=lambda j: j["started"])
    ]
    return {"running": any(job["running"] for job in jobs), "jobs": jobs}


@router.get("/regression")
async def regression_report():
    """Most recent post-rebuild throughput comparison, plus the known-good baselines."""
    return {"report": regression.last_report(), "baselines": regression.load_baselines()}


@router.post("/regression/run")
async def run_regression_guard(commit: str = ""):
    """Measure every running cluster against its baseline without rebuilding."""
    if any(job["running"] for job in _jobs.values()):
        raise HTTPException(409, "a build is already running")
    return await asyncio.to_thread(regression.run_guard, commit)


@router.post("/regression/accept")
async def accept_regression_baseline():
    """Bless the latest measurement as the new known-good."""
    return regression.accept_current_as_baseline()
