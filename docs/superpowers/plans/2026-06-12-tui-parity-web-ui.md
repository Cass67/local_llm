# TUI Parity — Web UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fill every gap between the Textual TUI and the Svelte web UI so the web UI is a complete replacement for model management: search, install, edit, delete, run, status, plus the existing models/switch/logs/playground features.

**Architecture:** Backend wraps existing CLI scripts (`model-discovery.sh`, `model-fit.py`, `oc-local`, `model-manager.sh`) via subprocess — reuses battle-tested logic, no Python porting needed. Container already has bash/git/curl/jq. New API routes map to CLI commands. New Svelte panels consume them.

**Tech Stack:** FastAPI (subprocess calls), Svelte 5 (new panels + enhanced existing), existing CLI scripts mounted read-only into container.

---

## Architecture: CLI Wrapping Pattern

The container runs on ubt26 — same host as the GPU. No SSH needed. Backend calls scripts directly:

```
Web UI → FastAPI route → subprocess.run(script) → JSON response → UI renders
```

Scripts to mount (read-only):
- `/home/cass/git/local_llm/scripts/model-discovery.sh`
- `/home/cass/git/local_llm/scripts/model-fit.py`
- `/home/cass/git/local_llm/scripts/model-manager.sh`
- `/home/cass/git/local_llm/scripts/oc-local`

Add to `docker-compose.yml` volumes:
```yaml
- ${HOME}/git/local_llm/scripts:/scripts:ro
```

Add to `container/backend/config.py`:
```python
SCRIPTS_DIR = Path(os.environ.get("SCRIPTS_DIR", "/scripts"))
```

---

## Feature Gap Analysis

| TUI Screen | Feature | Web Status | Plan Task |
|---|---|---|---|
| SearchScreen | Search HuggingFace, score models | ❌ Missing | 5.1 |
| InstallScreen | Install candidate (download+benchmark+accept) | ❌ Missing | 5.2 |
| ListScreen | List accepted + disk-only models | ⚠️ Partial (accepted only) | 5.3 |
| DetailScreen | View model metadata/benchmark | ❌ Missing | 5.4 |
| EditModelScreen | Edit all config params, save, regenerate launcher | ❌ Missing | 5.5 |
| DeleteScreen | Multi-select delete accepted + cache | ❌ Missing | 5.6 |
| RunScreen | Run with profile cycle, runtime override | ⚠️ Partial (basic switch) | 5.7 |
| StatusScreen | Full status: target, running, downloads | ❌ Missing | 5.8 |
| HFCardScreen | View HuggingFace model card | ❌ Missing | 5.9 |
| InitScreen | Set target (local/remote) | ❌ Missing | 5.10 |

---

## File Structure

### New backend files:
- `container/backend/routes/search.py` — search + install endpoints
- `container/backend/routes/manage.py` — edit, delete, detail, status endpoints
- `container/backend/routes/init.py` — target config endpoint
- `container/backend/cli.py` — subprocess wrapper for all CLI calls

### New UI files:
- `ui/src/components/SearchPanel.svelte` — search input, results table, filter, pagination, sort
- `ui/src/components/InstallProgress.svelte` — multi-phase install progress UI
- `ui/src/components/DeletePanel.svelte` — multi-select delete with confirmation
- `ui/src/components/EditModelForm.svelte` — full config edit form
- `ui/src/components/ModelDetail.svelte` — metadata + benchmark viewer
- `ui/src/components/StatusPanel.svelte` — full status dashboard
- `ui/src/components/HFCardViewer.svelte` — markdown model card viewer
- `ui/src/components/RunPanel.svelte` — enhanced run with profile cycle + override
- `ui/src/routes/Search.svelte` — search route
- `ui/src/routes/Status.svelte` — status route

### Modified files:
- `container/docker-compose.yml` — add scripts volume
- `container/Dockerfile` — no change (scripts mounted, not built in)
- `container/backend/config.py` — add SCRIPTS_DIR
- `container/backend/main.py` — register new routers
- `ui/src/App.svelte` — add new routes
- `ui/src/components/Header.svelte` — add nav items (Search, Status)
- `ui/src/components/ModelsPanel.svelte` — add edit/delete/detail buttons
- `ui/src/lib/api.ts` — add new API functions
- `ui/src/lib/types.ts` — add new types

---

## Task 5.1: Backend CLI Wrapper + Search Endpoint

**Files:**
- Create: `container/backend/cli.py`
- Create: `container/backend/routes/search.py`
- Test: `container/tests/test_search.py`
- Modify: `container/backend/config.py`
- Modify: `container/docker-compose.yml`
- Modify: `container/backend/main.py`

- [ ] **Step 1: Add SCRIPTS_DIR to config.py**

Add after `LAUNCHERS_DIR` line in `container/backend/config.py`:

```python
SCRIPTS_DIR = Path(os.environ.get("SCRIPTS_DIR", "/scripts"))
```

- [ ] **Step 2: Add scripts volume to docker-compose.yml**

Add after the existing `~/.cache/huggingface:/models:ro` line in `container/docker-compose.yml` volumes:

```yaml
      - ${HOME}/git/local_llm/scripts:/scripts:ro
```

- [ ] **Step 3: Write the failing test**

```python
# container/tests/test_search.py
import json
import pytest
from unittest.mock import patch, MagicMock
from httpx import ASGITransport, AsyncClient
from backend.main import app


@pytest.mark.asyncio
async def test_search_returns_candidates():
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = json.dumps({
        "candidates": [
            {"repo": "TheBloke/qwen-Q6_K-GGUF", "score": 85, "best_quant": "Q6_K", "best_file": "qwen.Q6_K.gguf"},
            {"repo": "TheBloke/qwen-Q4_K_M-GGUF", "score": 72, "best_quant": "Q4_K_M", "best_file": "qwen.Q4_K_M.gguf"},
        ]
    })
    mock_result.stderr = ""

    with patch("backend.cli.subprocess.run", return_value=mock_result) as mock_run:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/search", params={"query": "qwen coding gguf"})

    assert response.status_code == 200
    data = response.json()
    assert len(data["candidates"]) == 2
    assert data["candidates"][0]["repo"] == "TheBloke/qwen-Q6_K-GGUF"
    assert data["candidates"][0]["score"] == 85
    mock_run.assert_called_once()
    cmd = mock_run.call_args[0][0]
    assert "model-discovery" in cmd[0] or any("model-discovery" in str(a) for a in cmd)


@pytest.mark.asyncio
async def test_search_no_results():
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = json.dumps({"candidates": []})
    mock_result.stderr = ""

    with patch("backend.cli.subprocess.run", return_value=mock_result):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/search", params={"query": "xyznonexistent"})

    assert response.status_code == 200
    data = response.json()
    assert data["candidates"] == []


@pytest.mark.asyncio
async def test_search_cli_failure():
    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stdout = ""
    mock_result.stderr = "discovery failed: network error"

    with patch("backend.cli.subprocess.run", return_value=mock_result):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/search", params={"query": "test"})

    assert response.status_code == 500
    assert "discovery failed" in response.json()["detail"].lower()
```

- [ ] **Step 4: Run test to verify it fails**

Run: `cd container && python -m pytest tests/test_search.py -v`
Expected: FAIL (no `/api/search` route, no `backend.cli` module)

- [ ] **Step 5: Create cli.py**

```python
# container/backend/cli.py
"""CLI wrapper: subprocess calls to model-manager scripts."""
import json
import subprocess
from pathlib import Path
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

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip()[:300] or "discovery failed")

    data = json.loads(result.stdout)
    return data.get("candidates", [])


def run_delete(repo: str, target: str) -> str:
    """Delete model via model-manager.sh delete. Returns 'ok' or error message."""
    cmd = ["bash", str(MODEL_MANAGER), "delete", repo, "--target", target, "--yes"]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if result.returncode == 0:
        return "ok"
    return f"error: {result.stderr.strip()[:200]}"


def run_update_launcher(family: str) -> str:
    """Regenerate launcher for family."""
    cmd = [str(MODEL_MANAGER), "update-launcher", "--family", family, "--yes"]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode == 0:
        return "ok"
    return f"warning: {(result.stderr or result.stdout or '').strip()[:200]}"


def run_start_server(family: str, profile: str, ctx_override: str | None = None) -> tuple[str, str]:
    """Start server via oc-local. Returns (status, message)."""
    if not OC_LOCAL.exists():
        return "error", "oc-local not found"

    cmd = ["bash", str(OC_LOCAL), family, profile]
    if ctx_override:
        cmd.extend(["--ctx", ctx_override])

    try:
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        deadline = __import__("time").monotonic() + 120
        last_stderr = ""
        while __import__("time").monotonic() < deadline:
            if process.poll() is not None:
                _, stderr = process.communicate(timeout=1)
                last_stderr = stderr.strip()
                break
            __import__("time").sleep(1)
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
```

- [ ] **Step 6: Create search route**

```python
# container/backend/routes/search.py
"""Search and install endpoints."""
import json
from fastapi import APIRouter, Query
from pydantic import BaseModel
from .. import cli

router = APIRouter(prefix="/api/search", tags=["search"])


@router.get("")
async def search_models(
    query: str = Query(..., min_length=1, max_length=200),
    limit: int = Query(default=30, ge=1, le=100),
):
    """Search HuggingFace for GGUF models. Runs model-discovery.sh."""
    try:
        candidates = cli.run_discovery(query, host=None, limit=limit)
    except RuntimeError as e:
        return {"candidates": [], "error": str(e)}
    except Exception as e:
        return {"candidates": [], "error": f"Search failed: {e}"}
    return {"candidates": candidates, "error": None}
```

- [ ] **Step 7: Register router in main.py**

Add to `container/backend/main.py` imports:
```python
from .routes.search import router as search_router
```

Add after existing `app.include_router` lines:
```python
app.include_router(search_router)
```

- [ ] **Step 8: Run test to verify it passes**

Run: `cd container && python -m pytest tests/test_search.py -v`
Expected: PASS (3 tests)

- [ ] **Step 9: Commit**

```bash
git add container/backend/cli.py container/backend/routes/search.py container/tests/test_search.py container/backend/config.py container/docker-compose.yml container/backend/main.py
git commit -m "feat: search endpoint wrapping model-discovery.sh"
```

---

## Task 5.2: Install Endpoint (Download + Benchmark + Accept)

**Files:**
- Modify: `container/backend/routes/search.py`
- Test: `container/tests/test_install.py`

The TUI install flow: select candidate → `model-manager.sh install` (downloads, benchmarks, writes accepted JSON, generates launcher). The web version calls the same CLI.

- [ ] **Step 1: Write the failing test**

```python
# container/tests/test_install.py
import json
import pytest
from unittest.mock import patch, MagicMock
from httpx import ASGITransport, AsyncClient
from backend.main import app


@pytest.mark.asyncio
async def test_install_model_success():
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = json.dumps({
        "status": "installed",
        "family": "qwen-test",
        "alias": "qwen-test-q6",
    })
    mock_result.stderr = ""

    with patch("backend.cli.subprocess.run", return_value=mock_result) as mock_run:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/api/search/install", json={
                "repo": "TheBloke/qwen-Q6_K-GGUF",
                "file": "qwen.Q6_K.gguf",
                "profile": "balanced",
            })

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "installed"


@pytest.mark.asyncio
async def test_install_model_failure():
    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stdout = ""
    mock_result.stderr = "download failed: disk full"

    with patch("backend.cli.subprocess.run", return_value=mock_result):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/api/search/install", json={
                "repo": "TheBloke/qwen-Q6_K-GGUF",
                "file": "qwen.Q6_K.gguf",
                "profile": "balanced",
            })

    assert response.status_code == 500
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd container && python -m pytest tests/test_install.py -v`
Expected: FAIL (no install endpoint)

- [ ] **Step 3: Add install endpoint to search.py**

Add to `container/backend/routes/search.py`:

```python
class InstallRequest(BaseModel):
    repo: str
    file: str
    profile: str = "balanced"


@router.post("/install")
async def install_model(req: InstallRequest):
    """Install a model candidate. Runs model-manager.sh install."""
    cmd = [
        "bash", str(cli.MODEL_MANAGER), "install",
        "--repo", req.repo,
        "--file", req.file,
        "--profile", req.profile,
        "--yes",
    ]
    try:
        result = __import__("subprocess").run(
            cmd, capture_output=True, text=True, timeout=600,
        )
    except __import__("subprocess").TimeoutExpired:
        return {"status": "error", "detail": "Install timed out (10 min)"}

    if result.returncode != 0:
        return {"status": "error", "detail": result.stderr.strip()[:300] or "install failed"}

    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"status": "ok", "detail": result.stdout.strip()[:200]}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd container && python -m pytest tests/test_install.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add container/backend/routes/search.py container/tests/test_install.py
git commit -m "feat: install endpoint wrapping model-manager install"
```

---

## Task 5.3: Enhanced List (Accepted + Disk-Only + Inventory)

**Files:**
- Modify: `container/backend/routes/models.py`
- Create: `container/backend/routes/manage.py`
- Test: `container/tests/test_manage.py`

Add disk-only models and inventory (remote GGUF files not yet accepted).

- [ ] **Step 1: Write the failing test**

```python
# container/tests/test_manage.py
import json
import pytest
from unittest.mock import patch, MagicMock
from httpx import ASGITransport, AsyncClient
from backend.main import app


@pytest.mark.asyncio
async def test_inventory_returns_disk_models():
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = (
        '{"repo":"TheBloke/qwen-GGUF","path":"/cache/qwen","file":"qwen.Q6_K.gguf","disk_gb":"12.3","gguf":"yes"}\n'
        '{"repo":"TheBloke/llama-GGUF","path":"/cache/llama","file":"llama.Q4_K_M.gguf","disk_gb":"5.1","gguf":"yes"}\n'
    )
    mock_result.stderr = ""

    with patch("backend.cli.subprocess.run", return_value=mock_result):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/inventory")

    assert response.status_code == 200
    data = response.json()
    assert len(data["models"]) == 2
    assert data["models"][0]["repo"] == "TheBloke/llama-GGUF"


@pytest.mark.asyncio
async def test_status_returns_full_state():
    with patch("backend.service.get_llama_server_status", return_value="active"):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/status")

    assert response.status_code == 200
    data = response.json()
    assert "target" in data
    assert "running" in data
    assert "accepted_count" in data
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd container && python -m pytest tests/test_manage.py -v`
Expected: FAIL (no `/api/inventory` or `/api/status`)

- [ ] **Step 3: Create manage.py with inventory, detail, delete, edit, status endpoints**

```python
# container/backend/routes/manage.py
"""Model management: inventory, detail, edit, delete, status."""
import json
import re
from pathlib import Path
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from .. import config, cli
from ..models import ModelInfo, ModelConfig
from ..service import get_llama_server_status, detect_running_model

router = APIRouter(prefix="/api", tags=["manage"])


# --- Inventory ---

@router.get("/inventory")
async def get_inventory():
    """List all GGUF models on disk (cache dirs)."""
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
            'repo': repo, 'path': path,
            'file': pathlib.Path(path).name,
            'disk_gb': f'{size/1_000_000_000:.1f}' if size else '-',
            'gguf': 'yes' if ggufs else 'no',
        }))
"""
    import subprocess
    try:
        result = subprocess.run(
            ["python3", "-c", script],
            capture_output=True, text=True, timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {"models": []}

    models = []
    for line in result.stdout.splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict) and item.get("repo"):
            models.append({str(k): str(v) for k, v in item.items()})
    models.sort(key=lambda m: m.get("repo", ""))
    return {"models": models}


# --- Detail ---

@router.get("/models/{family}/detail")
async def model_detail(family: str):
    """Return full accepted metadata for a model family."""
    safe = re.compile(r"^[A-Za-z0-9_.-]+$")
    if not safe.fullmatch(family) or ".." in family:
        raise HTTPException(400, "invalid family name")

    path = config.ACCEPTED_DIR / f"{family}.json"
    if not path.exists():
        raise HTTPException(404, f"family '{family}' not found")
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError) as e:
        raise HTTPException(500, f"corrupt metadata: {e}")

    return data


# --- Edit ---

class EditRequest(BaseModel):
    profile: str | None = None
    ctx: int | None = None
    batch: int | None = None
    ubatch: int | None = None
    ngl: int | None = None
    cache_type_k: str | None = None
    cache_type_v: str | None = None
    ctx_shift: str | None = None
    reasoning: bool | None = None
    backend: str | None = None
    visible_devices: str | None = None
    split_mode: str | None = None
    tensor_split: str | None = None
    flags: str | None = None


@router.put("/models/{family}")
async def edit_model(family: str, req: EditRequest):
    """Edit accepted model config. Writes metadata + regenerates launcher."""
    safe = re.compile(r"^[A-Za-z0-9_.-]+$")
    if not safe.fullmatch(family) or ".." in family:
        raise HTTPException(400, "invalid family name")

    path = config.ACCEPTED_DIR / f"{family}.json"
    if not path.exists():
        raise HTTPException(404, f"family '{family}' not found")

    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        raise HTTPException(500, "corrupt metadata")

    # Apply edits
    if req.profile is not None:
        data["profile"] = req.profile
    cfg = data.setdefault("config", {})
    for field in ("ctx", "batch", "ubatch", "ngl", "cache_type_k", "cache_type_v",
                  "ctx_shift", "visible_devices", "split_mode", "tensor_split", "flags"):
        val = getattr(req, field, None)
        if val is not None:
            cfg[field] = val
    if req.reasoning is not None:
        cfg["reasoning"] = req.reasoning
    if req.backend is not None:
        cfg["backend"] = req.backend

    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")

    # Regenerate launcher
    launcher_result = cli.run_update_launcher(family)
    return {"status": "ok", "launcher": launcher_result}


# --- Delete ---

class DeleteRequest(BaseModel):
    repos: list[str]


@router.post("/models/delete")
async def delete_models(req: DeleteRequest):
    """Delete one or more model repos. Removes accepted metadata + cache."""
    target = "local"  # Container runs on same host as GPU
    results = []
    for repo in req.repos:
        if not repo or len(repo) > 500:
            results.append({"repo": repo, "status": "error", "detail": "invalid repo"})
            continue
        result = cli.run_delete(repo, target)
        results.append({"repo": repo, "status": result})
    return {"results": results}


# --- Status ---

@router.get("/status")
async def full_status():
    """Full status dashboard: target, running model, accepted count, downloads."""
    # Read config
    config_file = config.RUNS_DIR / "config.json"
    target = "local"
    if config_file.exists():
        try:
            cfg = json.loads(config_file.read_text())
            target = cfg.get("target", "local")
        except (json.JSONDecodeError, OSError):
            pass

    # Running model
    running_info = detect_running_model()

    # Accepted count
    accepted_count = 0
    if config.ACCEPTED_DIR.exists():
        accepted_count = sum(
            1 for p in config.ACCEPTED_DIR.glob("*.json")
            if p.name != "default.json" and not p.is_symlink()
        )

    # Active downloads
    import subprocess
    downloads = []
    try:
        result = subprocess.run(
            ["pgrep", "-af", "[h]f download|[h]uggingface.*download"],
            capture_output=True, text=True, timeout=5,
        )
        for line in result.stdout.splitlines():
            parts = line.split()
            pid = parts[0] if parts else "?"
            repo = "?"
            if "download" in parts:
                idx = parts.index("download")
                if idx + 1 < len(parts):
                    repo = parts[idx + 1]
            downloads.append({"pid": pid, "repo": repo})
    except (OSError, subprocess.TimeoutExpired):
        pass

    return {
        "target": target,
        "running": running_info,
        "accepted_count": accepted_count,
        "default_set": (config.ACCEPTED_DIR / "default.json").exists(),
        "downloads": downloads,
    }
```

Add `detect_running_model` to `container/backend/service.py`:

```python
def detect_running_model() -> dict:
    """Detect currently running model via llama-server process."""
    import subprocess, json
    status = get_llama_server_status()
    if status != "active":
        return {"status": "inactive", "family": None, "ctx": None}

    try:
        result = subprocess.run(
            ["bash", "-c", "pid=$(pgrep -f llama-server | head -1); [ -n \"$pid\" ] && tr '\\0' '\\n' < /proc/$pid/cmdline || true"],
            capture_output=True, text=True, timeout=10,
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

    # Match to accepted model
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
```

- [ ] **Step 4: Register router in main.py**

```python
from .routes.manage import router as manage_router
app.include_router(manage_router)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd container && python -m pytest tests/test_manage.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add container/backend/routes/manage.py container/backend/service.py container/tests/test_manage.py container/backend/main.py
git commit -m "feat: inventory, detail, edit, delete, status endpoints"
```

---

## Task 5.4: Target Init Endpoint

**Files:**
- Create: `container/backend/routes/init.py`
- Test: `container/tests/test_init.py`

- [ ] **Step 1: Write the failing test**

```python
# container/tests/test_init.py
import json
import pytest
from pathlib import Path
from httpx import ASGITransport, AsyncClient
from backend.main import app
from backend import config


@pytest.mark.asyncio
async def test_init_sets_target(tmp_path):
    import backend.config as cfg
    old_runs = cfg.RUNS_DIR
    cfg.RUNS_DIR = tmp_path
    cfg.ACCEPTED_DIR = tmp_path / "accepted"

    try:
        (tmp_path / "accepted").mkdir(parents=True, exist_ok=True)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/api/init", json={"target": "local"})

        assert response.status_code == 200
        config_file = tmp_path / "config.json"
        assert config_file.exists()
        data = json.loads(config_file.read_text())
        assert data["target"] == "local"
    finally:
        cfg.RUNS_DIR = old_runs
        cfg.ACCEPTED_DIR = old_runs / "accepted"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd container && python -m pytest tests/test_init.py -v`
Expected: FAIL (no `/api/init`)

- [ ] **Step 3: Create init route**

```python
# container/backend/routes/init.py
"""Target initialization endpoint."""
import json
from pathlib import Path
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from ..config import RUNS_DIR

router = APIRouter(prefix="/api", tags=["init"])

SAFE_TARGET_PATTERN = __import__("re").compile(r"^local$|^remote:[A-Za-z0-9_.:-]+$")


class InitRequest(BaseModel):
    target: str


@router.post("/init")
async def init_target(req: InitRequest):
    """Set the management target (local or remote:<host>)."""
    if not SAFE_TARGET_PATTERN.match(req.target):
        raise HTTPException(400, f"invalid target: {req.target}")

    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    config_file = RUNS_DIR / "config.json"
    config_file.write_text(json.dumps({
        "target": req.target,
    }, indent=2) + "\n")

    return {"status": "ok", "target": req.target}
```

Register in main.py:
```python
from .routes.init import router as init_router
app.include_router(init_router)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd container && python -m pytest tests/test_init.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add container/backend/routes/init.py container/tests/test_init.py container/backend/main.py
git commit -m "feat: target init endpoint"
```

---

## Task 5.5: HF Card Viewer Endpoint

**Files:**
- Modify: `container/backend/routes/manage.py`
- Test: `container/tests/test_hfcard.py`

- [ ] **Step 1: Write the failing test**

```python
# container/tests/test_hfcard.py
import pytest
from unittest.mock import patch, MagicMock
from httpx import ASGITransport, AsyncClient
from backend.main import app


@pytest.mark.asyncio
async def test_hf_card_returns_markdown():
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "---\nlicense: apache-2.0\n---\n# Qwen Model\nGreat model."
    mock_result.stderr = ""

    with patch("backend.routes.manage.subprocess.run", return_value=mock_result):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/hfcard", params={"repo": "Qwen/Qwen2.5-7B"})

    assert response.status_code == 200
    data = response.json()
    assert "markdown" in data
    assert "Qwen Model" in data["markdown"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd container && python -m pytest tests/test_hfcard.py -v`
Expected: FAIL (no `/api/hfcard`)

- [ ] **Step 3: Add HF card endpoint to manage.py**

Add to `container/backend/routes/manage.py`:

```python
@router.get("/hfcard")
async def hf_card(repo: str = Query(..., min_length=1, max_length=500)):
    """Fetch HuggingFace model card as markdown."""
    import subprocess
    try:
        result = subprocess.run(
            ["curl", "-s", "-L", "-H", "Accept: text/markdown",
             f"https://huggingface.co/{repo}/raw/main/README.md"],
            capture_output=True, text=True, timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {"markdown": "Failed to fetch model card.", "error": True}

    if result.returncode != 0 or not result.stdout.strip():
        return {"markdown": "No model card available.", "error": True}

    return {"markdown": result.stdout, "error": False}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd container && python -m pytest tests/test_hfcard.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add container/backend/routes/manage.py container/tests/test_hfcard.py
git commit -m "feat: HF model card viewer endpoint"
```

---

## Task 5.6: Svelte Search Panel

**Files:**
- Create: `ui/src/components/SearchPanel.svelte`
- Create: `ui/src/routes/Search.svelte`
- Modify: `ui/src/App.svelte` (add route)
- Modify: `ui/src/components/Header.svelte` (add nav link)
- Modify: `ui/src/lib/api.ts` (add search functions)
- Modify: `ui/src/lib/types.ts` (add search types)

This is a large UI task. The search panel replicates SearchScreen from TUI:
- Search input → calls `/api/search`
- Results table with columns: #, Repo, Score, Quant
- Filter input for post-search filtering
- Sort toggle (score/repo/quant)
- Pagination (15 per page)
- Click row → install
- HF card button on selected row
- Multi-select with batch install

- [ ] **Step 1: Add types to types.ts**

```typescript
// Add to ui/src/lib/types.ts

export interface SearchCandidate {
  repo: string;
  score: number;
  best_quant: string;
  best_file: string;
}

export interface SearchResponse {
  candidates: SearchCandidate[];
  error: string | null;
}

export interface InstallRequest {
  repo: string;
  file: string;
  profile: string;
}

export interface InventoryModel {
  repo: string;
  path: string;
  file: string;
  disk_gb: string;
  gguf: string;
}

export interface StatusResponse {
  target: string;
  running: { status: string; family: string | null; ctx: number | null };
  accepted_count: number;
  default_set: boolean;
  downloads: Array<{ pid: string; repo: string }>;
}

export interface EditResponse {
  status: string;
  launcher: string;
}

export interface DeleteResponse {
  results: Array<{ repo: string; status: string }>;
}

export interface HFCardResponse {
  markdown: string;
  error: boolean;
}
```

- [ ] **Step 2: Add API functions to api.ts**

```typescript
// Add to ui/src/lib/api.ts

import type {
  SearchResponse, InstallRequest, InventoryModel, StatusResponse,
  EditResponse, DeleteResponse, HFCardResponse,
} from './types';

export async function searchModels(query: string, limit = 30): Promise<SearchResponse> {
  const res = await fetch(`${BASE}/api/search?query=${encodeURIComponent(query)}&limit=${limit}`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

export async function installModel(req: InstallRequest): Promise<any> {
  const res = await fetch(`${BASE}/api/search/install`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

export async function fetchInventory(): Promise<{ models: InventoryModel[] }> {
  const res = await fetch(`${BASE}/api/inventory`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

export async function fetchStatus(): Promise<StatusResponse> {
  const res = await fetch(`${BASE}/api/status`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

export async function fetchModelDetail(family: string): Promise<any> {
  const res = await fetch(`${BASE}/api/models/${encodeURIComponent(family)}/detail`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

export async function editModel(family: string, edits: any): Promise<EditResponse> {
  const res = await fetch(`${BASE}/api/models/${encodeURIComponent(family)}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(edits),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

export async function deleteModels(repos: string[]): Promise<DeleteResponse> {
  const res = await fetch(`${BASE}/api/models/delete`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ repos }),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

export async function fetchHFCard(repo: string): Promise<HFCardResponse> {
  const res = await fetch(`${BASE}/api/hfcard?repo=${encodeURIComponent(repo)}`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

export async function initTarget(target: string): Promise<any> {
  const res = await fetch(`${BASE}/api/init`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ target }),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}
```

- [ ] **Step 3: Create SearchPanel.svelte**

Create `ui/src/components/SearchPanel.svelte` — full search UI with:
- Query input + search button
- Results table (#, Repo, Score, Quant) with row click → install
- Filter input for live filtering
- Sort toggle button (score/repo/quant)
- Prev/Next pagination
- Multi-select toggle (Space) + batch install (Enter)
- HF card button (opens modal)
- Install confirmation dialog
- Per-candidate install status

Component is ~200 lines of Svelte 5 with $state, $derived, $effect.

- [ ] **Step 4: Create Search.svelte route**

```svelte
<!-- ui/src/routes/Search.svelte -->
<script lang="ts">
  import SearchPanel from '../components/SearchPanel.svelte';
</script>

<div class="route">
  <h2>Search & Install</h2>
  <SearchPanel />
</div>
```

- [ ] **Step 5: Add route to App.svelte**

Add to routes object in `ui/src/App.svelte`:
```typescript
import Search from './routes/Search.svelte';
// Add to routes:
'/search': Search,
```

- [ ] **Step 6: Add nav link to Header.svelte**

Add `<a href="#/search">Search</a>` in the nav section.

- [ ] **Step 7: Build and verify**

```bash
cd ui && npm run build
```

- [ ] **Step 8: Commit**

```bash
git add ui/src/ container/ui-dist/
git commit -m "feat: search panel with results table, filter, pagination, install"
```

---

## Task 5.7: Svelte Edit + Detail + Delete UI

**Files:**
- Create: `ui/src/components/EditModelForm.svelte`
- Create: `ui/src/components/ModelDetail.svelte`
- Create: `ui/src/components/DeletePanel.svelte`
- Modify: `ui/src/components/ModelCard.svelte` (add Edit/Delete/Detail buttons)

This task adds action buttons to each ModelCard and creates the corresponding modal/panel components:
- Edit button → opens EditModelForm with all config fields
- Detail button → opens ModelDetail showing full metadata
- Delete button → opens DeletePanel with multi-select confirmation

- [ ] **Step 1: Create EditModelForm.svelte**

Form with all TUI edit fields: profile, ctx, batch, ubatch, ngl, cache_type_k/v, ctx_shift, reasoning, backend, visible_devices, split_mode, tensor_split, flags.

On save: calls `editModel(family, edits)` API.

~150 lines.

- [ ] **Step 2: Create ModelDetail.svelte**

Read-only view of full accepted metadata: repo, alias, quant, profile, launcher, config fields, profiles dict, benchmark data.

Calls `fetchModelDetail(family)` API.

~80 lines.

- [ ] **Step 3: Create DeletePanel.svelte**

Multi-select delete:
- Lists all accepted models with checkboxes
- Shows disk_gb for each (from inventory)
- Select All / Select None buttons
- Delete button with confirmation dialog
- Calls `deleteModels(repos)` API

~120 lines.

- [ ] **Step 4: Add buttons to ModelCard.svelte**

Add Edit, Detail, Delete buttons to each card's footer. Wire to parent callbacks.

- [ ] **Step 5: Build and verify**

```bash
cd ui && npm run build
```

- [ ] **Step 6: Commit**

```bash
git add ui/src/components/ ui/src/lib/
git commit -m "feat: edit, detail, delete UI components"
```

---

## Task 5.8: Svelte Status Dashboard

**Files:**
- Create: `ui/src/components/StatusPanel.svelte`
- Create: `ui/src/routes/Status.svelte`
- Modify: `ui/src/App.svelte` (add route)
- Modify: `ui/src/components/Header.svelte` (add nav link)

Replicates StatusScreen from TUI:
- Target display
- Running model indicator with ctx
- Accepted count
- Default model indicator
- Model table with running highlight
- Edit/restart buttons per model
- Active downloads table

~150 lines.

- [ ] **Step 1: Create StatusPanel.svelte**

Dashboard calling `/api/status` with auto-refresh every 10s.

- [ ] **Step 2: Create Status.svelte route**

- [ ] **Step 3: Add route + nav**

- [ ] **Step 4: Build and verify**

- [ ] **Step 5: Commit**

```bash
git add ui/src/ container/ui-dist/
git commit -m "feat: status dashboard with running model, downloads, restart"
```

---

## Task 5.9: Enhanced Run Panel (Profile Cycle + Override)

**Files:**
- Create: `ui/src/components/RunPanel.svelte`
- Modify: `ui/src/components/ModelCard.svelte` (enhance profile selection)

Replicates RunScreen from TUI:
- Enhanced model list showing all profiles per model
- Profile cycle button (like TUI's `p` key)
- Runtime override dialog (ctx + profile for one-time run)
- Stop server button
- Start status spinner + health check

- [ ] **Step 1: Enhance ModelCard with profile cycle + override**

Add profile cycle button next to select. Add "Override" button that opens a dialog for one-time ctx/profile override.

- [ ] **Step 2: Add stop endpoint to backend**

Add to `container/backend/routes/switch.py`:
```python
@router.post("/stop")
async def stop_server():
    from ..cli import run_stop_server
    result = run_stop_server()
    return {"status": result}
```

- [ ] **Step 3: Build and verify**

- [ ] **Step 4: Commit**

```bash
git add ui/src/ container/
git commit -m "feat: enhanced run panel with profile cycle and runtime override"
```

---

## Task 5.10: HF Card Modal

**Files:**
- Create: `ui/src/components/HFCardViewer.svelte`

Reusable modal that fetches and renders HF model card markdown:
- Takes `repo` prop
- Calls `/api/hfcard?repo=...`
- Renders markdown (use simple markdown-to-HTML or preformatted)
- Close button

~60 lines.

- [ ] **Step 1: Create HFCardViewer.svelte**

- [ ] **Step 2: Wire into SearchPanel and ModelCard**

- [ ] **Step 3: Build and verify**

- [ ] **Step 4: Commit**

```bash
git add ui/src/components/HFCardViewer.svelte
git commit -m "feat: HF model card viewer modal"
```

---

## Task 5.11: Redeploy and Integration Test

**Files:**
- Modify: `container/docker-compose.yml` (add scripts volume)
- Modify: `container/Dockerfile` (if needed)

- [ ] **Step 1: Rebuild container with scripts volume**

```bash
rsync -az ~/git/local_llm/container/ ubt26:~/git/local_llm/container/
cd ~/git/local_llm/ui && npm run build
rsync -az ~/git/local_llm/container/ ubt26:~/git/local_llm/container/
ssh ubt26 "cd ~/git/local_llm/container && docker compose down && docker compose build && docker compose up -d"
```

- [ ] **Step 2: Verify all endpoints**

```bash
curl -s http://ubt26:3100/api/health
curl -s http://ubt26:3100/api/status
curl -s "http://ubt26:3100/api/search?query=qwen+gguf&limit=5"
curl -s http://ubt26:3100/api/inventory
```

- [ ] **Step 3: Open UI in browser and verify all panels**

Navigate to each route:
- `#/models` — list, edit, delete, switch
- `#/search` — search, install
- `#/logs` — SSE log viewer
- `#/playground` — chat
- `#/status` — dashboard

- [ ] **Step 4: Commit**

```bash
git commit -m "chore: redeploy with full TUI parity features"
```

---

## Self-Review

**1. Spec coverage:**
- ✅ Search (Task 5.1 backend, 5.6 UI)
- ✅ Install (Task 5.2 backend, 5.6 UI)
- ✅ List (existing + Task 5.3 inventory)
- ✅ Detail (Task 5.3 backend, 5.7 UI)
- ✅ Edit (Task 5.3 backend, 5.7 UI)
- ✅ Delete (Task 5.3 backend, 5.7 UI)
- ✅ Run with profiles + override (Task 5.9)
- ✅ Status dashboard (Task 5.3 backend, 5.8 UI)
- ✅ HF card viewer (Task 5.5 backend, 5.10 UI)
- ✅ Init target (Task 5.4 backend)

**2. Placeholder scan:**
- Tasks 5.6–5.10 have abbreviated UI code descriptions (component structure described but not full Svelte code). This is intentional — the exact UI code is better written during implementation with the full context of existing components. The backend code is fully specified.

**3. Type consistency:**
- All API types defined in Task 5.6 types.ts match the endpoint signatures in Tasks 5.1–5.5.
- `SearchCandidate` matches `run_discovery` return format.
- `EditRequest` fields match `EditRequest` pydantic model.
- `DeleteRequest.repos` matches backend `DeleteRequest.repos`.
