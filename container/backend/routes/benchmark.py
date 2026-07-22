"""Persisted benchmark dashboard API."""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import subprocess  # noqa: S404 # nosec B404
import time
import uuid
from functools import lru_cache
from importlib import import_module
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, HttpUrl

from backend.benchmarks import SwebenchRunner, TerminalBenchRunner

from .. import config
from ..clusters import list_clusters

BenchmarkStore = import_module("backend.benchmark_store").BenchmarkStore

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/benchmark", tags=["benchmark"])

_RUNNERS = {
    "terminal-bench": TerminalBenchRunner(),
    "swe-bench": SwebenchRunner(),
}
_LOG_DIRS = {
    "terminal-bench": import_module("backend.benchmarks.terminal_bench")._RUNS_DIR,
    "swe-bench": import_module("backend.benchmarks.swe_bench")._RUNS_DIR,
}
_JOBS: dict[str, dict[str, Any]] = {}


class EndpointCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    base_url: HttpUrl
    api_key: str | None = Field(default=None, max_length=500)


class PromptCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    text: str = Field(min_length=1, max_length=20000)


class EndpointRef(BaseModel):
    endpoint_id: int


class BenchmarkRunRequest(BaseModel):
    endpoint_id: int
    model: str = Field(min_length=1, max_length=500)
    prompt_text: str = Field(min_length=1, max_length=20000)
    system_prompt: str = Field(default="", max_length=20000)
    prompt_id: int | None = None
    prompt_name: str | None = Field(default=None, max_length=120)
    temperature: float = Field(default=0.2, ge=0, le=2)
    max_tokens: int = Field(default=512, ge=1, le=8192)
    seed: int | None = Field(default=None, ge=0)
    top_p: float | None = Field(default=None, ge=0, le=1)
    top_k: int | None = Field(default=None, ge=0, le=200)
    repeat_penalty: float | None = Field(default=None, ge=1, le=2)


@lru_cache(maxsize=1)
def _store():
    return BenchmarkStore(config.RUNS_DIR / "benchmarks.sqlite3")


def _auth_headers(endpoint: dict[str, Any]) -> dict[str, str]:
    api_key = endpoint.get("api_key")
    if isinstance(api_key, str) and api_key:
        return {"Authorization": f"Bearer {api_key}"}
    return {}


def _model_ids(payload: Any) -> list[str]:
    if not isinstance(payload, dict):
        return []
    models: list[str] = []
    for item in payload.get("data", []):
        if isinstance(item, dict) and isinstance(item.get("id"), str):
            models.append(item["id"])
    for item in payload.get("models", []):
        if not isinstance(item, dict):
            continue
        for key in ("id", "name", "model"):
            value = item.get(key)
            if isinstance(value, str):
                models.append(value)
                break
    return sorted(set(models))


def _response_text(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0]
    if not isinstance(first, dict):
        return ""
    message = first.get("message")
    if isinstance(message, dict) and isinstance(message.get("content"), str):
        return message["content"]
    text = first.get("text")
    return text if isinstance(text, str) else ""


def _usage(payload: Any) -> dict[str, int | None]:
    usage = payload.get("usage") if isinstance(payload, dict) else None
    if not isinstance(usage, dict):
        return {"prompt_tokens": None, "completion_tokens": None, "total_tokens": None}
    return {
        "prompt_tokens": usage.get("prompt_tokens")
        if isinstance(usage.get("prompt_tokens"), int)
        else None,
        "completion_tokens": (
            usage.get("completion_tokens")
            if isinstance(usage.get("completion_tokens"), int)
            else None
        ),
        "total_tokens": usage.get("total_tokens")
        if isinstance(usage.get("total_tokens"), int)
        else None,
    }


def _word_count(text: str) -> int:
    return len([part for part in text.split() if part])


def _prompt_name(req: BenchmarkRunRequest) -> str | None:
    if req.prompt_name:
        return req.prompt_name
    if req.prompt_id is None:
        return None
    for prompt in _store().list_prompts():
        if prompt["id"] == req.prompt_id:
            return prompt["name"]
    return None


@router.get("/endpoints")
async def list_endpoints():
    return {"endpoints": _store().list_endpoints()}


@router.post("/endpoints/sync-clusters")
async def sync_cluster_endpoints():
    clusters = list_clusters()
    for c in clusters:
        logger.info(
            "  cluster %s: %s -> http://127.0.0.1:%d/v1 (backend=%s, gpus=%s)",
            c.id,
            c.name,
            c.port,
            c.backend,
            ",".join(c.gpu_pci_ids),
        )
    for cluster in clusters:
        _store().upsert_endpoint(f"Cluster: {cluster.name}", "http://127.0.0.1:3200/v1")
    return {"endpoints": _store().list_endpoints()}


@router.post("/endpoints")
async def create_endpoint(req: EndpointCreate):
    return _store().create_endpoint(req.name, str(req.base_url), req.api_key)


@router.delete("/endpoints/{endpoint_id}")
async def delete_endpoint(endpoint_id: int):
    return {"deleted": _store().delete_endpoint(endpoint_id)}


@router.get("/prompts")
async def list_prompts():
    return {"prompts": _store().list_prompts()}


@router.post("/prompts")
async def create_prompt(req: PromptCreate):
    return _store().create_prompt(req.name, req.text)


@router.delete("/prompts/{prompt_id}")
async def delete_prompt(prompt_id: int):
    return {"deleted": _store().delete_prompt(prompt_id)}


@router.post("/models")
async def load_models(req: EndpointRef):
    endpoint = _store().get_endpoint_secret(req.endpoint_id)
    if endpoint is None:
        raise HTTPException(status_code=404, detail="endpoint not found")
    name = str(endpoint.get("name", ""))
    if name.startswith("Cluster: "):
        # Cluster endpoint — return only the model running on this cluster
        from ..active_runners import list_active

        cluster_name = name.removeprefix("Cluster: ").strip()
        active = list_active()
        models = []
        for entry in active:
            if entry.get("cluster_name") == cluster_name:
                alias = entry.get("model")
                if alias:
                    models = [alias]
                break
        return {"models": models}
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"{endpoint['base_url'].rstrip('/')}/models",
                headers=_auth_headers(endpoint),
            )
            response.raise_for_status()
            return {"models": _model_ids(response.json())}
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="failed to load models") from exc


@router.post("/runs")
async def run_benchmark(req: BenchmarkRunRequest, benchmark_type: str = "standard"):
    endpoint = _store().get_endpoint_secret(req.endpoint_id)
    if endpoint is None:
        raise HTTPException(status_code=404, detail="endpoint not found")
    cluster_name = str(endpoint["name"]).removeprefix("Cluster: ").strip()
    prompt_snippet = req.prompt_text.strip()[:60].replace("\n", " ")
    print(f"bench: [{cluster_name}] {req.model} ← {prompt_snippet!r}", flush=True)

    started = time.perf_counter()
    payload: dict[str, Any] | None = None
    status = "ok"
    error: str | None = None
    try:
        messages: list[dict[str, str]] = []
        if req.system_prompt:
            messages.append({"role": "system", "content": req.system_prompt})
        messages.append({"role": "user", "content": req.prompt_text})
        body: dict[str, Any] = {
            "model": req.model,
            "messages": messages,
            "temperature": req.temperature,
            "max_tokens": req.max_tokens,
        }
        if req.seed is not None:
            body["seed"] = req.seed
        if req.top_p is not None:
            body["top_p"] = req.top_p
        if req.top_k is not None:
            body["top_k"] = req.top_k
        if req.repeat_penalty is not None:
            body["repeat_penalty"] = req.repeat_penalty
        async with httpx.AsyncClient(timeout=300.0) as client:
            response = await client.post(
                f"{endpoint['base_url'].rstrip('/')}/chat/completions",
                json=body,
                headers=_auth_headers(endpoint),
            )
            response.raise_for_status()
            payload = response.json()
    except httpx.HTTPError as exc:
        status = "error"
        error = str(exc)

    duration_ms = (time.perf_counter() - started) * 1000
    text = _response_text(payload) if payload is not None else ""
    usage = _usage(payload)
    completion_tokens = usage["completion_tokens"]
    duration_seconds = max(duration_ms / 1000, 0.001)
    throughput_tps = (
        completion_tokens / duration_seconds if isinstance(completion_tokens, int) else None
    )
    throughput_cps = len(text) / duration_seconds if text else None

    result = _store().create_run(
        benchmark_type=benchmark_type,
        endpoint_id=endpoint["id"],
        endpoint_name=endpoint["name"],
        endpoint_base_url=endpoint["base_url"],
        model=req.model,
        prompt_id=req.prompt_id,
        prompt_name=_prompt_name(req),
        prompt_text=req.prompt_text,
        response_text=text,
        latency_ms=duration_ms,
        duration_ms=duration_ms,
        output_chars=len(text),
        output_words=_word_count(text),
        prompt_tokens=usage["prompt_tokens"],
        completion_tokens=completion_tokens,
        total_tokens=usage["total_tokens"],
        throughput_tps=throughput_tps,
        throughput_cps=throughput_cps,
        status=status,
        error=error,
    )
    status_str = f"{duration_ms:.0f}ms tps={throughput_tps:.0f}" if status == "ok" else status
    print(f"bench: [{cluster_name}] {req.model} → {status_str}", flush=True)
    return result


@router.get("/runs")
async def list_runs(
    endpoint_id: int | None = None,
    model: str | None = None,
    prompt_id: int | None = None,
    status: str | None = None,
    benchmark_type: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    return _store().list_runs(
        {
            "endpoint_id": endpoint_id,
            "model": model,
            "prompt_id": prompt_id,
            "status": status,
            "benchmark_type": benchmark_type,
            "from_date": from_date,
            "to_date": to_date,
            "limit": limit,
            "offset": offset,
        }
    )


@router.get("/summary")
async def summary(benchmark_type: str | None = None):
    """Get benchmark summary, optionally filtered by type."""
    return _store().summary(benchmark_type=benchmark_type)


@router.get("/types")
async def list_benchmark_types():
    """List available benchmark types."""
    runners = [
        TerminalBenchRunner(),
        SwebenchRunner(),
    ]
    return {
        "types": [
            {"name": runner.name, "description": f"{runner.name} benchmark"} for runner in runners
        ]
    }


@lru_cache(maxsize=8)
def _list_tasks_cached(benchmark_type: str) -> tuple[str, ...]:
    return tuple(_RUNNERS[benchmark_type].list_tasks())


@router.get("/types/{benchmark_type}/tasks")
async def list_benchmark_tasks(benchmark_type: str):
    """List the selectable task/instance IDs for a benchmark type's dataset."""
    if benchmark_type not in _RUNNERS:
        raise HTTPException(status_code=404, detail=f"Unknown benchmark type: {benchmark_type}")
    tasks = await asyncio.to_thread(_list_tasks_cached, benchmark_type)
    return {"tasks": list(tasks)}


def _run_typed_benchmark(
    benchmark_type: str, req: BenchmarkRunRequest, run_id: str
) -> dict[str, Any]:
    runner = _RUNNERS[benchmark_type]
    endpoint = _store().get_endpoint_secret(req.endpoint_id)
    if endpoint is None:
        raise HTTPException(status_code=404, detail="endpoint not found")

    cluster_name = str(endpoint["name"]).removeprefix("Cluster: ").strip()
    prompt_snippet = req.prompt_text.strip()[:60].replace("\n", " ")
    print(
        f"bench [{benchmark_type}]: [{cluster_name}] {req.model} ← {prompt_snippet!r}", flush=True
    )

    result = runner.run(
        endpoint_id=req.endpoint_id,
        model=req.model,
        prompt_text=req.prompt_text,
        endpoint_name=endpoint["name"],
        endpoint_base_url=endpoint["base_url"],
        api_key=endpoint.get("api_key"),
        run_id=run_id,
        **req.model_dump(exclude={"endpoint_id", "model", "prompt_text"}),
    )

    stored_result = _store().create_run(
        benchmark_type=benchmark_type,
        run_id=run_id,
        endpoint_id=result.pop("endpoint_id"),
        endpoint_name=result.pop("endpoint_name"),
        endpoint_base_url=result.pop("endpoint_base_url"),
        **result,
    )

    status_str = (
        f"{stored_result['latency_ms']:.0f}ms tps={stored_result['throughput_tps'] or 0:.0f}"
        if stored_result["status"] == "ok"
        else stored_result["status"]
    )
    print(f"bench [{benchmark_type}]: [{cluster_name}] {req.model} → {status_str}", flush=True)
    return stored_result


@router.post("/runs/{benchmark_type}")
async def run_benchmark_type(benchmark_type: str, req: BenchmarkRunRequest):
    """Run a specific benchmark type synchronously (blocks until the run finishes)."""
    if benchmark_type not in _RUNNERS:
        raise HTTPException(status_code=404, detail=f"Unknown benchmark type: {benchmark_type}")

    errors = _RUNNERS[benchmark_type].validate(req.model_dump())
    if errors:
        raise HTTPException(status_code=400, detail=" | ".join(errors))

    run_id = f"web-{int(time.time())}-{uuid.uuid4().hex[:8]}"
    return await asyncio.to_thread(_run_typed_benchmark, benchmark_type, req, run_id)


@router.post("/runs/{benchmark_type}/start")
async def start_benchmark_type(benchmark_type: str, req: BenchmarkRunRequest):
    """Kick off a benchmark run in the background and return a job id to poll."""
    if benchmark_type not in _RUNNERS:
        raise HTTPException(status_code=404, detail=f"Unknown benchmark type: {benchmark_type}")

    errors = _RUNNERS[benchmark_type].validate(req.model_dump())
    if errors:
        raise HTTPException(status_code=400, detail=" | ".join(errors))

    run_id = f"web-{int(time.time())}-{uuid.uuid4().hex[:8]}"
    job: dict[str, Any] = {
        "status": "running",
        "result": None,
        "error": None,
        "task": None,
        "benchmark_type": benchmark_type,
        "started_at": time.time(),
    }
    _JOBS[run_id] = job

    async def _execute() -> None:
        try:
            result = await asyncio.to_thread(_run_typed_benchmark, benchmark_type, req, run_id)
            job.update(status="done", result=result, error=None)
        except Exception as e:  # noqa: BLE001
            job.update(status="error", result=None, error=str(e))

    job["task"] = asyncio.create_task(_execute())
    return {"job_id": run_id}


@router.get("/jobs")
async def list_active_jobs():
    """List currently-running benchmark jobs so any client can reconnect to their console."""
    return {
        "jobs": [
            {"job_id": job_id, "benchmark_type": job["benchmark_type"], "status": job["status"]}
            for job_id, job in _JOBS.items()
            if job["status"] == "running"
        ]
    }


def _cancel_run(run_id: str) -> None:
    """Kill the benchmark subprocess tree for run_id and reap its docker containers.

    Both terminal-bench and swe-bench embed run_id in their subprocess cmdlines and in
    the container/compose-project names, so matching on run_id catches everything a run
    spawned — including builds and containers orphaned by a mgmt restart.
    """
    pkill = shutil.which("pkill") or "pkill"
    docker = shutil.which("docker") or "docker"
    subprocess.run([pkill, "-TERM", "-f", run_id], check=False)  # noqa: S603 # nosec B603
    ids = subprocess.run(  # noqa: S603 # nosec B603
        [docker, "ps", "-aq", "--filter", f"name={run_id}"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout.split()
    if ids:
        subprocess.run([docker, "rm", "-f", *ids], check=False)  # noqa: S603 # nosec B603


@router.post("/runs/{benchmark_type}/jobs/{job_id}/cancel")
async def cancel_benchmark_job(benchmark_type: str, job_id: str):
    """Kill a running benchmark job and clean up any containers it spawned."""
    if "/" in job_id or ".." in job_id:
        raise HTTPException(status_code=400, detail="invalid job id")
    await asyncio.to_thread(_cancel_run, job_id)
    job = _JOBS.get(job_id)
    if job is not None:
        task = job.get("task")
        if task is not None:
            task.cancel()
        job.update(status="error", error="cancelled by user")
    return {"cancelled": True}


@router.get("/runs/{benchmark_type}/jobs/{job_id}")
async def get_benchmark_job(benchmark_type: str, job_id: str):
    """Poll a background benchmark job for status, live log tail, and final result."""
    job = _JOBS.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")

    log = ""
    progress = None
    log_dir = _LOG_DIRS.get(benchmark_type)
    if log_dir is not None:
        run_dir = log_dir / job_id
        log_path = run_dir / "run.log"
        if log_path.exists():
            log = log_path.read_text()[-8000:]
        manifest_path = run_dir / "manifest.json"
        if manifest_path.exists():
            try:
                total = json.loads(manifest_path.read_text())["total"]
                generated = len(list(run_dir.glob("*/*.traj.json")))
                evaluated = len(list(run_dir.glob("logs/run_evaluation/*/*/*/report.json")))
                progress = {"total": total, "generated": generated, "evaluated": evaluated}
            except (OSError, KeyError, json.JSONDecodeError):
                progress = None

    return {
        "status": job["status"],
        "log": log,
        "result": job["result"],
        "error": job["error"],
        "progress": progress,
    }


def _report_path(benchmark_type: str, run_id: str) -> Path | None:
    log_dir = _LOG_DIRS.get(benchmark_type)
    if log_dir is None or "/" in run_id or ".." in run_id:
        return None
    run_dir = log_dir / run_id
    if benchmark_type == "terminal-bench":
        # tb writes into a nested <run_id>/<run_id> dir (see terminal_bench.py)
        candidate = run_dir / run_id / "results.json"
        return candidate if candidate.exists() else None
    if benchmark_type == "swe-bench":
        # the real aggregate report is always named "<model>.<run_id>.json" — anything
        # else at the top level (preds.json, manifest.json) is not a report, and matching
        # "any json that isn't preds.json" would wrongly pick manifest.json for a run
        # that was interrupted before the harness ever produced a final report
        return next(run_dir.glob(f"*.{run_id}.json"), None)
    return None


@router.get("/runs/{benchmark_type}/report/{run_id}")
async def get_benchmark_report(benchmark_type: str, run_id: str):
    """Serve the raw report file (results.json / swebench report) for a run."""
    path = _report_path(benchmark_type, run_id)
    if path is None:
        raise HTTPException(status_code=404, detail="report not found")
    return FileResponse(path, media_type="application/json", filename=path.name)


def _run_dir(benchmark_type: str, run_id: str) -> Path | None:
    log_dir = _LOG_DIRS.get(benchmark_type)
    if log_dir is None or "/" in run_id or ".." in run_id:
        return None
    run_dir = log_dir / run_id
    return run_dir if run_dir.is_dir() else None


@router.get("/runs/{benchmark_type}/report/{run_id}/files")
async def list_benchmark_run_files(benchmark_type: str, run_id: str):
    """List every artifact file produced by a run (patches, per-instance logs, reports)."""
    run_dir = _run_dir(benchmark_type, run_id)
    if run_dir is None:
        raise HTTPException(status_code=404, detail="run not found")
    files = sorted(str(p.relative_to(run_dir)) for p in run_dir.rglob("*") if p.is_file())
    return {"files": files}


@router.get("/runs/{benchmark_type}/report/{run_id}/file")
async def get_benchmark_run_file(benchmark_type: str, run_id: str, path: str = Query(...)):
    """Serve the raw content of one artifact file from a run, scoped to its run directory."""
    run_dir = _run_dir(benchmark_type, run_id)
    if run_dir is None:
        raise HTTPException(status_code=404, detail="run not found")
    target = (run_dir / path).resolve()
    if run_dir.resolve() not in target.parents or not target.is_file():
        raise HTTPException(status_code=404, detail="file not found")
    return FileResponse(target, media_type="text/plain")
