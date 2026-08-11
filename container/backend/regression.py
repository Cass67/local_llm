"""Post-rebuild throughput guard.

Upstream llama.cpp regularly changes performance on this hardware in both
directions, and a rebuild is the moment it happens. After every successful build
we re-measure a fixed prompt on each running cluster and compare against the last
known-good number for that exact cluster+model+profile.

The baseline only ratchets forward on non-regressions, so a slow build cannot
quietly become the new normal.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from . import active_runners, config
from .clusters import list_active, list_clusters, read_active

logger = logging.getLogger(__name__)

# Same prompt every time — the number is only meaningful against its own history.
GUARD_PROMPT = (
    "Write a Python function called merge_intervals that merges a list of "
    "overlapping [start, end] intervals and returns them sorted. Include a "
    "docstring and three example assertions."
)
GUARD_MAX_TOKENS = 256
GUARD_REPEATS = 3
REGRESSION_THRESHOLD = 0.05  # 5% slower than known-good is a regression


def _baselines_path():
    return config.RUNS_DIR / "regression_baselines.json"


def _report_path():
    return config.RUNS_DIR / "regression_last.json"


def _read_json(path, default):
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return default


def _write_json(path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))


def load_baselines() -> dict[str, Any]:
    return _read_json(_baselines_path(), {})


def last_report() -> dict[str, Any] | None:
    return _read_json(_report_path(), None)


def baseline_key(cluster_id: str, family: str, profile: str) -> str:
    return f"{cluster_id}:{family}:{profile}"


def _measure_cluster(port: int, model: str) -> dict[str, Any]:
    """Median decode throughput over GUARD_REPEATS runs of the fixed prompt."""
    from .sweep import _chat_once

    runs = [
        _chat_once(port, model, GUARD_PROMPT, "", GUARD_MAX_TOKENS, 300.0)
        for _ in range(GUARD_REPEATS)
    ]

    def median(key: str) -> float | None:
        values = sorted(r[key] for r in runs if r.get(key) is not None)
        return values[len(values) // 2] if values else None

    return {"decode_tps": median("decode_tps"), "prompt_tps": median("prompt_tps")}


def _verdict(current: float | None, baseline: float | None) -> tuple[str, float | None]:
    if current is None:
        return "unmeasured", None
    if baseline is None:
        return "baseline", None
    delta = (current - baseline) / baseline
    if delta < -REGRESSION_THRESHOLD:
        return "regressed", delta
    if delta > REGRESSION_THRESHOLD:
        return "improved", delta
    return "ok", delta


def run_guard(commit: str = "", *, restart: bool = True) -> dict[str, Any]:
    """Re-measure every running cluster and diff against its known-good baseline."""
    baselines = load_baselines()
    clusters = {c.id: c for c in list_clusters()}
    entries: list[dict[str, Any]] = []

    for active in list_active():
        cluster_id = str(active.get("cluster_id") or "")
        cluster = clusters.get(cluster_id)
        if cluster is None:
            continue
        family = str(active.get("family") or "")
        profile = str(active.get("profile") or "")
        model = str(active.get("model") or family)
        key = baseline_key(cluster_id, family, profile)
        prior = baselines.get(key) or {}

        entry: dict[str, Any] = {
            "cluster_id": cluster_id,
            "cluster_name": cluster.name,
            "family": family,
            "profile": profile,
            "baseline_tps": prior.get("decode_tps"),
            "baseline_commit": prior.get("commit"),
        }
        try:
            if restart:
                # A rebuilt image only takes effect on a fresh container.
                accepted = json.loads((config.ACCEPTED_DIR / f"{family}.json").read_text())
                accepted["profile"] = profile
                active_runners.start(cluster, accepted)
                refreshed = read_active(cluster_id) or {}
                entry["warnings"] = refreshed.get("warnings") or []
            entry.update(_measure_cluster(cluster.port, model))
        except Exception as exc:  # noqa: BLE001 — one dead cluster must not hide the others
            entry.update(decode_tps=None, prompt_tps=None, error=str(exc)[:500])
            logger.warning("regression guard failed on %s: %s", cluster_id, exc)

        verdict, delta = _verdict(entry.get("decode_tps"), entry.get("baseline_tps"))
        entry["verdict"] = verdict
        entry["delta_pct"] = round(delta * 100, 1) if delta is not None else None
        entries.append(entry)

        # Ratchet: only a run that did not regress becomes the new known-good.
        if verdict in ("baseline", "ok", "improved") and entry.get("decode_tps"):
            baselines[key] = {
                "decode_tps": entry["decode_tps"],
                "prompt_tps": entry.get("prompt_tps"),
                "commit": commit,
                "ts": time.time(),
            }

    _write_json(_baselines_path(), baselines)
    report = {
        "ts": time.time(),
        "commit": commit,
        "threshold_pct": REGRESSION_THRESHOLD * 100,
        "clusters": entries,
        "regressions": [e for e in entries if e["verdict"] == "regressed"],
    }
    _write_json(_report_path(), report)
    for entry in report["regressions"]:
        logger.warning(
            "REGRESSION after %s: cluster=%s %s %.1f tps vs baseline %.1f (%.1f%%)",
            commit[:12] or "manual run",
            entry["cluster_name"],
            entry["family"],
            entry["decode_tps"],
            entry["baseline_tps"],
            entry["delta_pct"],
        )
    return report


def accept_current_as_baseline() -> dict[str, Any]:
    """Bless the most recent measurement — for a regression you have decided to keep."""
    report = last_report()
    if not report:
        return {"updated": 0}
    baselines = load_baselines()
    updated = 0
    for entry in report.get("clusters", []):
        if not entry.get("decode_tps"):
            continue
        key = baseline_key(entry["cluster_id"], entry["family"], entry["profile"])
        baselines[key] = {
            "decode_tps": entry["decode_tps"],
            "prompt_tps": entry.get("prompt_tps"),
            "commit": report.get("commit", ""),
            "ts": time.time(),
        }
        updated += 1
    _write_json(_baselines_path(), baselines)
    return {"updated": updated}
