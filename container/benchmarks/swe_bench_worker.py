#!/usr/bin/env python3
"""Swe-Bench Worker Service."""

import os
import time
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()


class BenchmarkJob(BaseModel):
    """Request payload for a benchmark job."""

    prompt_text: str
    model: str
    endpoint_id: int
    endpoint_name: str
    endpoint_base_url: str


@app.post("/run")
async def run_benchmark(job: BenchmarkJob) -> dict[str, Any]:
    """Execute a swe-bench job."""
    start_time = time.perf_counter()
    status = "ok"
    error = None
    response_text = ""
    completion_tokens = None

    try:
        # In a real implementation, this would:
        # 1. Parse the prompt to extract the code task
        # 2. Create a test environment
        # 3. Execute the LLM's solution
        # 4. Run tests and validate results
        # For now, we just return a mock successful response

        # Simulate some processing
        time.sleep(0.1)

        response_text = "Solution applied successfully."
        completion_tokens = len(response_text.split())

        duration_ms = (time.perf_counter() - start_time) * 1000
        duration_seconds = max(duration_ms / 1000, 0.001)

        return {
            "endpoint_id": job.endpoint_id,
            "endpoint_name": job.endpoint_name,
            "endpoint_base_url": job.endpoint_base_url,
            "model": job.model,
            "prompt_text": job.prompt_text,
            "response_text": response_text,
            "latency_ms": duration_ms,
            "duration_ms": duration_ms,
            "output_chars": len(response_text),
            "output_words": len(response_text.split()),
            "prompt_tokens": None,
            "completion_tokens": completion_tokens,
            "total_tokens": completion_tokens,
            "throughput_tps": completion_tokens / duration_seconds if completion_tokens else None,
            "throughput_cps": len(response_text) / duration_seconds if response_text else None,
            "status": status,
            "error": error,
        }
    except Exception as e:
        error = str(e)
        status = "error"

    duration_ms = (time.perf_counter() - start_time) * 1000
    return {
        "endpoint_id": job.endpoint_id,
        "endpoint_name": job.endpoint_name,
        "endpoint_base_url": job.endpoint_base_url,
        "model": job.model,
        "prompt_text": job.prompt_text,
        "response_text": "",
        "latency_ms": duration_ms,
        "duration_ms": duration_ms,
        "output_chars": 0,
        "output_words": 0,
        "prompt_tokens": None,
        "completion_tokens": None,
        "total_tokens": None,
        "throughput_tps": None,
        "throughput_cps": None,
        "status": status,
        "error": error,
    }


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy", "service": "swe-bench-worker"}


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("BENCHMARK_PORT", 3102))
    uvicorn.run(app, host="0.0.0.0", port=port)
