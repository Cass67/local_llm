"""Persisted benchmark dashboard API."""

from __future__ import annotations

import logging
import time
from functools import lru_cache
from importlib import import_module
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, HttpUrl

from .. import config
from ..clusters import list_clusters

BenchmarkStore = import_module("backend.benchmark_store").BenchmarkStore

# Import benchmark runners
from backend.benchmarks import SwebenchRunner, TerminalBenchRunner

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/benchmark", tags=["benchmark"])


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
    synced = [
        _store().upsert_endpoint(f"Cluster: {cluster.name}", "http://127.0.0.1:3200/v1")
        for cluster in clusters
    ]
    return {"endpoints": synced}


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
    cluster_name = str(endpoint.get("name", "")).removeprefix("Cluster: ").strip()
    if cluster_name:
        # Cluster endpoint — return only the model running on this cluster
        from ..active_runners import list_active

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
async def summary(
    benchmark_type: str | None = None,
):
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


@router.post("/runs/{benchmark_type}")
async def run_benchmark_type(benchmark_type: str, req: BenchmarkRunRequest):
    """Run a specific benchmark type."""
    # Map benchmark type to runner
    runners = {
        "terminal-bench": TerminalBenchRunner(),
        "swe-bench": SwebenchRunner(),
    }

    if benchmark_type not in runners:
        raise HTTPException(status_code=404, detail=f"Unknown benchmark type: {benchmark_type}")

    runner = runners[benchmark_type]

    # Validate request
    errors = runner.validate(req.model_dump())
    if errors:
        raise HTTPException(status_code=400, detail=" | ".join(errors))

    endpoint = _store().get_endpoint_secret(req.endpoint_id)
    if endpoint is None:
        raise HTTPException(status_code=404, detail="endpoint not found")

    cluster_name = str(endpoint["name"]).removeprefix("Cluster: ").strip()
    prompt_snippet = req.prompt_text.strip()[:60].replace("\n", " ")
    print(
        f"bench [{benchmark_type}]: [{cluster_name}] {req.model} ← {prompt_snippet!r}", flush=True
    )

    # Run the benchmark
    result = runner.run(
        endpoint_id=req.endpoint_id,
        model=req.model,
        prompt_text=req.prompt_text,
        endpoint_name=endpoint["name"],
        endpoint_base_url=endpoint["base_url"],
        worker_port=runner.worker_port,
        **req.model_dump(exclude={"endpoint_id", "model", "prompt_text"}),
    )

    # Store the result
    stored_result = _store().create_run(
        benchmark_type=benchmark_type,
        endpoint_id=result.pop("endpoint_id"),
        endpoint_name=result.pop("endpoint_name"),
        endpoint_base_url=result.pop("endpoint_base_url"),
        **result,
    )

    status_str = (
        f"{stored_result['latency_ms']:.0f}ms tps={stored_result['throughput_tps']:.0f}"
        if stored_result["status"] == "ok"
        else stored_result["status"]
    )
    print(f"bench [{benchmark_type}]: [{cluster_name}] {req.model} → {status_str}", flush=True)
    return stored_result


@router.get("/summary")
async def summary():
    return _store().summary()
