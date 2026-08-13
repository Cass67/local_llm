"""llama.cpp upstream update check + runner image rebuild via Docker socket."""

import asyncio
import json
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

from .. import config, regression, runtime

router = APIRouter(prefix="/api/update", tags=["update"])

GITHUB_REPOS = "https://api.github.com/repos"
GITHUB_API = f"{GITHUB_REPOS}/ggml-org/llama.cpp"
COMMIT_LABEL = "llama.cpp.commit"
RUNNER_SRC_DIR = Path(os.environ.get("RUNNER_SRC_DIR", "/app/runner"))
BUILD_LOG = config.STATE_DIR / "runner-build.log"

_BACKENDS = ("vulkan", "rocm", "cuda")

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


@router.get("/commit/{sha}")
async def commit_detail(sha: str):
    """Full commit, touched files, and the PR it came from (body + discussion)."""
    if not re.fullmatch(r"[0-9a-fA-F]{7,40}", sha):
        raise HTTPException(400, "not a commit sha")

    async with httpx.AsyncClient(timeout=20.0) as client:

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


def _run_agents_build(versions: dict[str, str]) -> None:
    build_args = []
    for agent_id, version in versions.items():
        build_args += ["--build-arg", f"{AGENT_PACKAGES[agent_id][1]}={version}"]
    with open(BUILD_LOG, "w") as log:
        _build["current"] = "agents"
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
        _build["results"]["agents"] = code
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
                    _build["results"]["agents"] = 1
                log.flush()
    _build["current"] = None
    _build["running"] = False


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

    with _build_lock:
        if _build["running"]:
            raise HTTPException(409, "a build is already running")
        _build.update(
            running=True, backends=["agents"], current=None, started=time.time(), results={}
        )
    threading.Thread(target=_run_agents_build, args=(versions,), daemon=True).start()
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
        resp = await client.get(f"{GITHUB_REPOS}/{svc['repo']}/commits/{svc['branch']}")
        head = resp.json()["sha"] if resp.status_code == 200 else None
        row["latest"] = head[:12] if head else None
        row["current"] = revision[:12] if revision else None
        if revision and head:
            cmp_resp = await client.get(
                f"{GITHUB_REPOS}/{svc['repo']}/compare/{revision}...{svc['branch']}"
            )
            if cmp_resp.status_code == 200:
                row["behind"] = cmp_resp.json().get("ahead_by", 0)
                row["outdated"] = row["behind"] > 0
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
    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
        try:
            rows = [await _service_row(client, sid, svc) for sid, svc in SERVICES.items()]
        except httpx.HTTPError as e:
            raise HTTPException(502, f"upstream unreachable: {e}") from e
    return {"services": rows}


def _run_service_update(service_id: str, svc: dict, ref: str | None) -> None:
    with open(BUILD_LOG, "w") as log:
        _build["current"] = service_id
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
        _build["results"][service_id] = code
        if code == 0:
            try:
                _recreate_container(svc["container"], svc["image"])
                log.write(f"recreated {svc['container']}\n")
            except (RuntimeError, OSError) as exc:
                log.write(f"failed to recreate {svc['container']}: {exc}\n")
                _build["results"][service_id] = 1
            log.flush()
    _build["current"] = None
    _build["running"] = False


@router.post("/services/{service_id}/build")
async def start_service_update(service_id: str):
    """Pull or rebuild one supporting container, then re-create it at the new image."""
    svc = SERVICES.get(service_id)
    if not svc:
        raise HTTPException(404, f"unknown service '{service_id}'")

    ref = None
    if svc["kind"] == "git-build":
        async with httpx.AsyncClient(timeout=20.0) as client:
            try:
                ref = await _latest_tag(client, svc["repo"], svc["series"])
            except httpx.HTTPError as e:
                raise HTTPException(502, f"GitHub unreachable: {e}") from e
        if not ref:
            raise HTTPException(502, f"no {svc['series']}x release found for {svc['repo']}")

    with _build_lock:
        if _build["running"]:
            raise HTTPException(409, "a build is already running")
        _build.update(
            running=True, backends=[service_id], current=None, started=time.time(), results={}
        )
    threading.Thread(target=_run_service_update, args=(service_id, svc, ref), daemon=True).start()
    return {"status": "started", "ref": ref}


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
