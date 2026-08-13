"""Category-sliced speculative-decoding acceptance (nvidia/SPEED-Bench).

Our spec-decoding numbers were all measured on hand-picked code-echo prompts,
which is exactly the workload bias SPEED-Bench exists to expose: acceptance on
code echo says nothing about acceptance on prose or multilingual. This sweeps a
fixed number of prompts per semantic domain and reports acceptance per domain.

draft_n / draft_n_accepted come straight out of llama-server's `timings`, so
there is nothing to scrape. Prompts are fetched from the HF rows API and cached
in the state dir, never vendored: the NVIDIA Evaluation Dataset License covers
evaluation use, not redistribution.

That licensing is also why 494 of the 880 rows ship as a placeholder string
rather than real text. Benchmarking a placeholder is worse than useless -- the
model rambles, the drafter predicts its own rambling, and you measure ~100%
acceptance that means nothing -- so they are dropped, loudly. Hydrate them with
NVIDIA's prepare.py and point PROMPTS_JSONL at the output for full coverage.
"""

from __future__ import annotations

import collections
import json
import logging
import statistics
import time
from pathlib import Path
from typing import Any

import httpx

from . import config
from .clusters import ClusterDef

logger = logging.getLogger(__name__)

ROWS_API = (
    "https://datasets-server.huggingface.co/rows"
    "?dataset=nvidia%2FSPEED-Bench&config=qualitative&split=test"
)
TOTAL_ROWS = 880
PLACEHOLDER = "SHOULD BE FETCHED FROM THE SOURCE"
# Greedy: sampling noise swamps the acceptance-rate differences we are measuring.
TEMPERATURE = 0.0


def _cache_path() -> Path:
    return config.RUNS_DIR / "speed-bench-qualitative.json"


def report_path() -> Path:
    return config.RUNS_DIR / "speed_bench_last.json"


def last_report() -> dict[str, Any] | None:
    try:
        return json.loads(report_path().read_text())
    except (OSError, json.JSONDecodeError):
        return None


def _fetch_rows() -> list[dict[str, Any]]:
    cache = _cache_path()
    try:
        return json.loads(cache.read_text())
    except (OSError, json.JSONDecodeError):
        pass
    rows: list[dict[str, Any]] = []
    with httpx.Client(timeout=60.0) as client:
        for off in range(0, TOTAL_ROWS, 100):
            resp = client.get(f"{ROWS_API}&offset={off}&length=100")
            resp.raise_for_status()
            rows += [r["row"] for r in resp.json()["rows"]]
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(rows))
    return rows


def _hydrated_rows(jsonl_dir: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    src = Path(jsonl_dir)
    paths = [src] if src.is_file() else sorted(src.glob("*.jsonl"))
    for path in paths:
        with open(path) as fh:
            rows += [json.loads(line) for line in fh if line.strip()]
    for row in rows:
        # prepare.py emits chat-format `messages` (all user-role) rather than `turns`
        if "turns" not in row:
            row["turns"] = [m["content"] for m in row["messages"] if m["role"] == "user"]
    return rows


def _is_placeholder(row: dict[str, Any]) -> bool:
    return any(PLACEHOLDER in (turn or "") for turn in row["turns"])


def load_prompts(jsonl_dir: str = "") -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Usable prompts, plus the per-category count of what was dropped."""
    rows = _hydrated_rows(jsonl_dir) if jsonl_dir else []
    if not rows:
        # Nothing hydrated (or the path is wrong): fall back to the HF rows API,
        # which still gives 386 real prompts out of the 880.
        rows = _fetch_rows()
    # Placeholders first, then de-duplicate: prepare.py's variants (qualitative
    # and qualitative-nohle) share question_ids, and dropping the placeholder
    # copy first is what keeps the hydrated one.
    keep: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not _is_placeholder(row):
            keep.setdefault(row["question_id"], row)
    # Only count a row as lost if no file hydrated it -- a placeholder that its
    # sibling file supplies for real is not missing.
    missing = {r["question_id"]: r["category"] for r in rows if r["question_id"] not in keep}
    dropped = collections.Counter(missing.values())
    return list(keep.values()), dict(dropped)


def categories(jsonl_dir: str = "") -> dict[str, Any]:
    """What can actually be run, and what is missing because it never hydrated."""
    rows, dropped = load_prompts(jsonl_dir)
    usable = collections.Counter(r["category"] for r in rows)
    names = sorted(set(usable) | set(dropped))
    return {
        "categories": [
            {"name": name, "usable": usable.get(name, 0), "placeholders": dropped.get(name, 0)}
            for name in names
        ],
        "usable_total": sum(usable.values()),
        "placeholder_total": sum(dropped.values()),
        "hydrated": bool(jsonl_dir),
    }


def _chat(port: int, model: str, messages: list[dict], max_tokens: int, timeout: float) -> dict:
    body = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": TEMPERATURE,
        # Each turn must pay its own prefill: a warm cache would let the drafter
        # ride on tokens this run did not actually predict.
        "cache_prompt": False,
    }
    with httpx.Client(timeout=timeout) as client:
        resp = client.post(f"http://127.0.0.1:{port}/v1/chat/completions", json=body)
        resp.raise_for_status()
        return resp.json()


def run_row(port: int, model: str, row: dict[str, Any], max_tokens: int, timeout: float) -> dict:
    """One SPEED-Bench item, all its turns, aggregated."""
    messages: list[dict] = []
    agg = dict.fromkeys(("prompt_n", "predicted_n", "draft_n", "draft_n_accepted"), 0)
    speeds: list[float] = []
    for turn in row["turns"]:
        messages.append({"role": "user", "content": turn})
        payload = _chat(port, model, messages, max_tokens, timeout)
        choice = payload["choices"][0]["message"]
        messages.append(
            {
                "role": "assistant",
                # Reasoning models return empty content with the tokens in reasoning_content.
                "content": choice.get("content") or choice.get("reasoning_content") or "",
            }
        )
        timings = payload.get("timings") or {}
        for key in agg:
            agg[key] += timings.get(key, 0)
        speeds.append(timings.get("predicted_per_second") or 0.0)

    draft_n, accepted, predicted = agg["draft_n"], agg["draft_n_accepted"], agg["predicted_n"]
    return {
        "category": row["category"],
        "question_id": row["question_id"],
        "multiturn": bool(row.get("multiturn")),
        "prompt_n": agg["prompt_n"],
        "predicted_n": predicted,
        "draft_n": draft_n,
        "draft_accepted": accepted,
        "accept_pct": round(100.0 * accepted / draft_n, 1) if draft_n else 0.0,
        # How much of the output the drafter even attempted: a great acceptance
        # rate over 5% of tokens is not a speedup.
        "cover_pct": round(100.0 * draft_n / predicted, 1) if predicted else 0.0,
        "tg_tok_s": round(statistics.mean(speeds), 2) if speeds else 0.0,
    }


def summarise(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Per-category totals. Acceptance is pooled over tokens, not averaged over rows."""
    per_category = []
    for name in sorted({r["category"] for r in rows}):
        sel = [r for r in rows if r["category"] == name]
        draft = sum(r["draft_n"] for r in sel)
        accepted = sum(r["draft_accepted"] for r in sel)
        per_category.append(
            {
                "category": name,
                "n": len(sel),
                "accept_pct": round(100.0 * accepted / draft, 1) if draft else 0.0,
                "cover_pct": round(statistics.mean(r["cover_pct"] for r in sel), 1),
                "tg_tok_s": round(statistics.mean(r["tg_tok_s"] for r in sel), 2),
            }
        )
    draft_all = sum(r["draft_n"] for r in rows)
    accepted_all = sum(r["draft_accepted"] for r in rows)
    return {
        "per_category": per_category,
        "overall": {
            "n": len(rows),
            "accept_pct": round(100.0 * accepted_all / draft_all, 1) if draft_all else 0.0,
            "cover_pct": round(statistics.mean([r["cover_pct"] for r in rows]), 1) if rows else 0.0,
            "tg_tok_s": round(statistics.mean([r["tg_tok_s"] for r in rows]), 2) if rows else 0.0,
        },
    }


def select_rows(
    prompts: list[dict[str, Any]], wanted: list[str], per_category: int
) -> list[dict[str, Any]]:
    by_category: dict[str, list[dict[str, Any]]] = {}
    for row in prompts:
        if wanted and row["category"] not in wanted:
            continue
        by_category.setdefault(row["category"], []).append(row)
    selected = []
    for name in sorted(by_category):
        selected += by_category[name][:per_category]
    return selected


def _write_report(
    cluster: ClusterDef,
    model: str,
    max_tokens: int,
    results: list[dict[str, Any]],
    *,
    cancelled: bool,
    in_progress: bool,
) -> dict[str, Any]:
    report = {
        "ts": time.time(),
        "cluster_id": cluster.id,
        "cluster_name": cluster.name,
        "model": model,
        "max_tokens": max_tokens,
        "cancelled": cancelled,
        "in_progress": in_progress,
        "rows": results,
        **summarise(results),
    }
    path = report_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2))
    return report


def run_sweep(
    cluster: ClusterDef,
    model: str,
    rows: list[dict[str, Any]],
    max_tokens: int,
    timeout: float,
    job: dict[str, Any],
) -> dict[str, Any]:
    """Measure every selected row, updating `job` as it goes so the UI can follow."""
    results: list[dict[str, Any]] = []
    for index, row in enumerate(rows, start=1):
        if job.get("cancel"):
            break
        job.update(done=index - 1, current=row["category"])
        try:
            results.append(run_row(cluster.port, model, row, max_tokens, timeout))
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            # One bad row must not throw away an hour of sweeping.
            logger.warning("speed-bench row %s failed: %s", row.get("question_id"), exc)
            job.setdefault("errors", []).append(f"{row.get('question_id', '?')}: {exc}"[:300])
        job["rows"] = results
        # Checkpoint: job state is in memory, so a full sweep is an hour of GPU
        # time that a container restart would otherwise erase completely.
        if results:
            _write_report(cluster, model, max_tokens, results, cancelled=False, in_progress=True)
    job.update(done=len(results), current=None)

    return _write_report(
        cluster,
        model,
        max_tokens,
        results,
        cancelled=bool(job.get("cancel")),
        in_progress=False,
    )
