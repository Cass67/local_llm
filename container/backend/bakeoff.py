"""Run the same measurements across several models, back to back.

The leaderboard can only compare what has been measured the same way, and filling
it by hand means switching model, benchmarking, switching again — an afternoon of
clicking for a handful of rows. This walks a list of model+profile pairs on one
cluster: load, warm up, time N completions, optionally score the golden set, move
on. Everything it records goes through the same store the manual paths use, so the
rows are directly comparable with runs made from the Benchmarks tab.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from . import active_runners, config, quality
from .benchmark_store import BenchmarkStore
from .clusters import ClusterDef
from .power import PowerSampler, tokens_per_watt
from .sweep import _chat_once

logger = logging.getLogger(__name__)

DEFAULT_PROMPT = (
    "Write a Python class `LRUCache` with get and put in O(1), using a dict and a "
    "doubly linked list. Include a short docstring and three assertions."
)


@dataclass
class BakeoffEntry:
    family: str
    profile: str = ""


@dataclass
class BakeoffJob:
    """Live state for one bake-off, polled by the UI while it runs."""

    id: str
    cluster_id: str
    total: int
    status: str = "running"
    current: str = ""
    log: list[str] = field(default_factory=list)
    results: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
    cancelled: bool = False
    started_at: float = field(default_factory=time.time)

    def say(self, message: str) -> None:
        stamp = time.strftime("%H:%M:%S")
        self.log.append(f"[{stamp}] {message}")
        logger.info("bakeoff %s: %s", self.id, message)

    def snapshot(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "cluster_id": self.cluster_id,
            "status": self.status,
            "current": self.current,
            "done": len(self.results),
            "total": self.total,
            "log": self.log[-200:],
            "results": self.results,
            "error": self.error,
            "elapsed_s": round(time.time() - self.started_at, 1),
        }


def load_accepted(family: str) -> dict[str, Any]:
    """Read accepted metadata for a family. ValueError, not HTTPException — this
    runs in a background job, not a request handler."""
    path = config.ACCEPTED_DIR / f"{family}.json"
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"model family '{family}' not found")
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"corrupt metadata for '{family}'") from exc
    if not isinstance(data, dict):
        raise ValueError(f"invalid metadata for '{family}'")
    return data


def _measure_one(
    port: int,
    alias: str,
    prompt: str,
    max_tokens: int,
    timeout: float,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """One timed completion with wall power sampled across it."""
    sampler = PowerSampler()
    sampler.__enter__()
    try:
        completion = _chat_once(port, alias, prompt, "", max_tokens, timeout)
    finally:
        sampler.__exit__()
    return completion, sampler.result()


def _record(
    store: BenchmarkStore,
    cluster: ClusterDef,
    alias: str,
    profile: str,
    prompt: str,
    completion: dict[str, Any],
    power: dict[str, Any],
) -> dict[str, Any]:
    text = completion.get("text") or ""
    tps = completion.get("decode_tps")
    wall_s = float(completion.get("wall_s") or 0.001)
    return store.create_run(
        benchmark_type="standard",
        endpoint_id=None,
        endpoint_name=f"Cluster: {cluster.name}",
        endpoint_base_url=f"http://127.0.0.1:{cluster.port}/v1",
        model=alias,
        prompt_name="bake-off",
        prompt_text=prompt,
        response_text=text,
        latency_ms=wall_s * 1000,
        duration_ms=wall_s * 1000,
        output_chars=len(text),
        output_words=len([w for w in text.split() if w]),
        completion_tokens=completion.get("completion_tokens"),
        throughput_tps=tps,
        throughput_cps=len(text) / wall_s if text else None,
        status="ok",
        error=None,
        psu_avg_w=power.get("psu_avg_w"),
        psu_peak_w=power.get("psu_peak_w"),
        gpu_avg_w=power.get("gpu_avg_w"),
        tps_per_watt=tokens_per_watt(tps, power.get("psu_avg_w")),
        profile=profile,
    )


def run_bakeoff(
    job: BakeoffJob,
    cluster: ClusterDef,
    entries: list[BakeoffEntry],
    *,
    prompt: str = DEFAULT_PROMPT,
    max_tokens: int = 256,
    repeats: int = 3,
    with_quality: bool = True,
    timeout: float = 600.0,
    store_factory: Callable[[], BenchmarkStore] | None = None,
) -> None:
    """Walk every entry on one cluster, recording runs as it goes.

    One entry failing does not end the bake-off — a model that will not load is
    exactly what a comparison is meant to surface, so it is logged and skipped.
    """
    store = (store_factory or _default_store)()
    for entry in entries:
        if job.cancelled:
            job.say("cancelled")
            break
        label = f"{entry.family}/{entry.profile or 'default'}"
        job.current = label
        try:
            accepted = load_accepted(entry.family)
            if entry.profile:
                accepted["profile"] = entry.profile
            alias = str(accepted.get("alias") or accepted.get("family") or entry.family)

            job.say(f"loading {label}")
            load_started = time.perf_counter()
            active_runners.start(cluster, accepted)
            load_s = round(time.perf_counter() - load_started, 1)
            job.say(f"{label} ready in {load_s}s — warming up")

            _measure_one(cluster.port, alias, prompt, max_tokens, timeout)

            runs: list[dict[str, Any]] = []
            for i in range(max(repeats, 1)):
                if job.cancelled:
                    break
                completion, power = _measure_one(cluster.port, alias, prompt, max_tokens, timeout)
                runs.append(
                    _record(
                        store,
                        cluster,
                        alias,
                        str(accepted.get("profile", "")),
                        prompt,
                        completion,
                        power,
                    )
                )
                job.say(
                    f"{label} run {i + 1}/{repeats}: {completion.get('decode_tps') or 0:.1f} tok/s"
                )

            scores = [r["throughput_tps"] for r in runs if r.get("throughput_tps")]
            result: dict[str, Any] = {
                "model": alias,
                "family": entry.family,
                "profile": str(accepted.get("profile", "")),
                "load_s": load_s,
                "runs": len(runs),
                "best_tps": round(max(scores), 2) if scores else None,
                "quality": None,
                "error": None,
            }

            if with_quality and not job.cancelled:
                job.say(f"{label}: scoring golden set")
                report = quality.run_quality(cluster.port, alias)
                store.create_quality_run(
                    model=alias,
                    profile=str(accepted.get("profile", "")),
                    cluster_id=cluster.id,
                    passed=report["passed"],
                    total=report["total"],
                    pass_rate=report["pass_rate"],
                    judge_mean=report["judge_mean"],
                )
                result["quality"] = report["pass_rate"]
                job.say(f"{label}: quality {report['passed']}/{report['total']}")

            job.results.append(result)
        except Exception as exc:  # noqa: BLE001
            job.say(f"{label} FAILED: {exc}")
            job.results.append(
                {
                    "model": entry.family,
                    "family": entry.family,
                    "profile": entry.profile,
                    "load_s": None,
                    "runs": 0,
                    "best_tps": None,
                    "quality": None,
                    "error": str(exc)[:300],
                }
            )

    job.current = ""
    if job.cancelled:
        job.status = "cancelled"
    else:
        job.status = "done"
        job.say(f"bake-off finished — {len(job.results)} entries")


def _default_store() -> BenchmarkStore:
    return BenchmarkStore(config.RUNS_DIR / "benchmarks.sqlite3")
