"""One timed completion, and the loop that repeats it.

Every measuring path here wants the same thing: warm up, run the same prompt N
times, take the median, and know what the wall socket was doing meanwhile. The
sweep, the bake-off and the post-rebuild guard all called their own copy of that
loop, which is how three of them ended up with three different ideas of what a
tok/s number includes. One implementation, so the numbers stay comparable.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from .benchmark_store import BenchmarkStore
from .clusters import ClusterDef
from .power import PowerSampler, tokens_per_watt

# The prompt every unattended measurement uses. Changing it invalidates the
# comparison between everything already recorded, so change it deliberately.
DEFAULT_PROMPT = (
    "Write a Python class `LRUCache` with get and put in O(1), using a dict and a "
    "doubly linked list. Include a short docstring and three assertions."
)


def chat_once(
    port: int,
    model: str,
    prompt: str,
    system_prompt: str = "",
    max_tokens: int = 256,
    timeout: float = 300.0,
) -> dict[str, Any]:
    """One non-streaming completion. Prefers llama-server's own timings block."""
    import httpx

    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})
    body = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0,
        "seed": 1234,
    }
    started = time.perf_counter()
    with httpx.Client(timeout=timeout) as client:
        response = client.post(f"http://127.0.0.1:{port}/v1/chat/completions", json=body)
        response.raise_for_status()
        payload = response.json()
    elapsed = max(time.perf_counter() - started, 0.001)

    usage = payload.get("usage") or {}
    completion_tokens = usage.get("completion_tokens")
    timings = payload.get("timings") or {}
    # llama-server measures decode without HTTP overhead; trust it when present.
    decode_tps = timings.get("predicted_per_second")
    if not isinstance(decode_tps, (int, float)):
        decode_tps = completion_tokens / elapsed if isinstance(completion_tokens, int) else None
    prompt_tps = timings.get("prompt_per_second")
    choices = payload.get("choices") or [{}]
    message = choices[0].get("message") or {}
    text = message.get("content") or ""
    return {
        "finish_reason": choices[0].get("finish_reason"),
        # Reasoning models spend the token budget here and can leave content empty.
        "reasoning_chars": len(message.get("reasoning_content") or ""),
        "decode_tps": round(float(decode_tps), 2) if decode_tps else None,
        "prompt_tps": round(float(prompt_tps), 2) if isinstance(prompt_tps, (int, float)) else None,
        "completion_tokens": completion_tokens,
        "wall_s": round(elapsed, 3),
        "text": text,
    }


def median(runs: list[dict[str, Any]], key: str) -> float | None:
    values = sorted(r[key] for r in runs if r.get(key) is not None)
    return values[len(values) // 2] if values else None


def measure(
    port: int,
    model: str,
    prompt: str,
    *,
    system_prompt: str = "",
    max_tokens: int = 256,
    repeats: int = 3,
    warmup: int = 1,
    timeout: float = 300.0,
    should_stop: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    """Warm up, time `repeats` completions, return the median with power.

    Warmups run outside the power window — the first completion after a load
    pays for page cache and clock ramp, and averaging that in makes a config
    look thirstier than it is.
    """
    stop = should_stop or (lambda: False)
    for _ in range(max(warmup, 0)):
        if stop():
            break
        chat_once(port, model, prompt, system_prompt, max_tokens, timeout)

    runs: list[dict[str, Any]] = []
    sampler = PowerSampler()
    with sampler:
        for _ in range(max(repeats, 1)):
            if stop():
                break
            runs.append(chat_once(port, model, prompt, system_prompt, max_tokens, timeout))
    power = sampler.result()
    if not runs:
        raise RuntimeError("cancelled before any measured run")

    decode_tps = median(runs, "decode_tps")
    return {
        "decode_tps": decode_tps,
        "prompt_tps": median(runs, "prompt_tps"),
        "wall_s": median(runs, "wall_s"),
        "completion_tokens": runs[-1].get("completion_tokens"),
        "runs": len(runs),
        **power,
        "tps_per_watt": tokens_per_watt(decode_tps, power.get("psu_avg_w")),
        "sample_text": runs[-1].get("text", "")[:2000],
    }


def record(
    store: BenchmarkStore,
    result: dict[str, Any],
    *,
    cluster: ClusterDef,
    model: str,
    profile: str,
    prompt: str,
    prompt_name: str,
    benchmark_type: str = "standard",
) -> dict[str, Any]:
    """File a `measure()` result in the same store the manual runs use."""
    text = result.get("sample_text") or ""
    tps = result.get("decode_tps")
    wall_s = float(result.get("wall_s") or 0.001)
    return store.create_run(
        benchmark_type=benchmark_type,
        endpoint_id=None,
        endpoint_name=f"Cluster: {cluster.name}",
        endpoint_base_url=f"http://127.0.0.1:{cluster.port}/v1",
        model=model,
        prompt_name=prompt_name,
        prompt_text=prompt,
        response_text=text,
        latency_ms=wall_s * 1000,
        duration_ms=wall_s * 1000,
        output_chars=len(text),
        output_words=len([w for w in text.split() if w]),
        completion_tokens=result.get("completion_tokens"),
        throughput_tps=tps,
        throughput_cps=len(text) / wall_s if text else None,
        status="ok",
        error=None,
        psu_avg_w=result.get("psu_avg_w"),
        psu_peak_w=result.get("psu_peak_w"),
        gpu_avg_w=result.get("gpu_avg_w"),
        tps_per_watt=result.get("tps_per_watt"),
        profile=profile,
    )


def default_store() -> BenchmarkStore:
    from . import config

    return BenchmarkStore(config.RUNS_DIR / "benchmarks.sqlite3")
