"""Profile autotuner — grid-search llama-server knobs and rank the results.

One combination at a time: patch the profile, relaunch the cluster, measure, move
on. Slow by nature (each step is a full model reload), so the loop is cancellable
and every result is persisted as it lands rather than at the end.
"""

from __future__ import annotations

import itertools
import json
import logging
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from . import active_runners, config, measure
from .clusters import ClusterDef, get_cluster
from .profile_lint import lint_profile

logger = logging.getLogger(__name__)

MAX_COMBOS = 64
_SWEEP_PROFILE_SUFFIX = "-sweep"


def sweeps_dir() -> Path:
    d = config.RUNS_DIR / "sweeps"
    d.mkdir(parents=True, exist_ok=True)
    return d


def expand_grid(grid: dict[str, list[Any]]) -> list[dict[str, Any]]:
    """Cartesian product of knob → candidate values, in a stable order."""
    keys = sorted(grid)
    values = [grid[k] for k in keys]
    if not keys or any(not v for v in values):
        return []
    return [dict(zip(keys, combo, strict=True)) for combo in itertools.product(*values)]


def _load_profiles() -> dict[str, Any]:
    try:
        return json.loads(config.PROFILES_CONFIG.read_text())
    except (OSError, json.JSONDecodeError):
        return {"families": {}}


def _save_profiles(data: dict[str, Any]) -> None:
    config.PROFILES_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    config.PROFILES_CONFIG.write_text(json.dumps(data, indent=2))


def base_profile_config(family: str, profile: str) -> dict[str, Any] | None:
    fam = _load_profiles().get("families", {}).get(family)
    if not isinstance(fam, dict):
        return None
    cfg = fam.get("profiles", {}).get(profile)
    return dict(cfg) if isinstance(cfg, dict) else None


def write_scratch_profile(family: str, name: str, cfg: dict[str, Any]) -> None:
    data = _load_profiles()
    fam = data.setdefault("families", {}).setdefault(family, {"default": name, "profiles": {}})
    fam["profiles"][name] = cfg
    _save_profiles(data)


def delete_scratch_profile(family: str, name: str) -> None:
    data = _load_profiles()
    fam = data.get("families", {}).get(family)
    if not isinstance(fam, dict):
        return
    fam.get("profiles", {}).pop(name, None)
    if fam.get("default") == name:
        fam["default"] = next(iter(fam.get("profiles", {})), "")
    _save_profiles(data)


def _resolve_accepted(family: str) -> dict[str, Any]:
    path = config.ACCEPTED_DIR / f"{family}.json"
    data = json.loads(path.read_text())
    if not isinstance(data, dict):
        raise ValueError("invalid model metadata")
    return data


def combo_label(base_profile: str, combo: dict[str, Any]) -> str:
    """Profile name a swept combination is recorded under in the benchmark store."""
    knobs = ",".join(f"{k}={v}" for k, v in sorted(combo.items()))
    return f"{base_profile}[{knobs}]"[:200]


class SweepJob:
    """Runs one grid sweep in a worker thread."""

    def __init__(
        self,
        *,
        family: str,
        cluster_id: str,
        base_profile: str,
        grid: dict[str, list[Any]],
        prompt_text: str,
        system_prompt: str = "",
        max_tokens: int = 256,
        repeats: int = 2,
        warmup: int = 1,
        objective: str = "decode_tps",
        request_timeout: float = 300.0,
        quality_gate: bool = False,
        min_pass_rate: float = 1.0,
        judge_url: str = "",
        judge_model: str = "",
    ) -> None:
        self.id = f"sweep-{int(time.time())}-{uuid.uuid4().hex[:6]}"
        self.family = family
        self.cluster_id = cluster_id
        self.base_profile = base_profile
        self.grid = grid
        self.prompt_text = prompt_text
        self.system_prompt = system_prompt
        self.max_tokens = max_tokens
        self.repeats = max(1, repeats)
        self.warmup = max(0, warmup)
        self.objective = objective
        self.request_timeout = request_timeout
        self.quality_gate = quality_gate
        self.min_pass_rate = min_pass_rate
        self.judge_url = judge_url
        self.judge_model = judge_model

        self.combos = expand_grid(grid)
        self.status = "pending"
        self.error: str | None = None
        self.results: list[dict[str, Any]] = []
        self.started_at = time.time()
        self.finished_at: float | None = None
        self._cancel = threading.Event()
        self._thread: threading.Thread | None = None

    # --- lifecycle ---

    @property
    def scratch_profile(self) -> str:
        return f"{self.base_profile}{_SWEEP_PROFILE_SUFFIX}"

    def cancel(self) -> None:
        self._cancel.set()

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True, name=self.id)
        self._thread.start()

    def snapshot(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "status": self.status,
            "error": self.error,
            "family": self.family,
            "cluster_id": self.cluster_id,
            "base_profile": self.base_profile,
            "objective": self.objective,
            "grid": self.grid,
            "total": len(self.combos),
            "completed": len(self.results),
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "results": self.results,
            "best": self.best(),
        }

    def best(self) -> dict[str, Any] | None:
        """Fastest combination that also passed the quality gate, if one is set."""
        ok = [r for r in self.results if r["status"] == "ok" and r.get(self.objective) is not None]
        if self.quality_gate:
            ok = [
                r for r in ok if (r.get("quality") or {}).get("pass_rate", 0) >= self.min_pass_rate
            ]
        if not ok:
            return None
        return max(ok, key=lambda r: r[self.objective])

    def persist(self) -> None:
        try:
            (sweeps_dir() / f"{self.id}.json").write_text(json.dumps(self.snapshot(), indent=2))
        except OSError as exc:
            logger.warning("could not persist sweep %s: %s", self.id, exc)

    # --- measurement ---

    def _measure(self, cluster: ClusterDef, model: str) -> dict[str, Any]:
        return measure.measure(
            cluster.port,
            model,
            self.prompt_text,
            system_prompt=self.system_prompt,
            max_tokens=self.max_tokens,
            repeats=self.repeats,
            warmup=self.warmup,
            timeout=self.request_timeout,
            should_stop=self._cancel.is_set,
        )

    # A sweep produces the most measurements of anything here, and until now they
    # only ever landed in the sweep's own JSON. File them where the history and
    # the leaderboard can see them — under the combination, not the scratch
    # profile, so a row says which knobs produced the number. Bookkeeping must
    # never sink a combination that measured fine, hence the broad except.

    def _record(self, cluster: ClusterDef, model: str, label: str, result: dict[str, Any]) -> None:
        try:
            measure.record(
                measure.default_store(),
                result,
                cluster=cluster,
                model=model,
                profile=label,
                prompt=self.prompt_text,
                prompt_name=f"sweep {self.id}",
                benchmark_type="sweep",
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("sweep %s could not record run: %s", self.id, exc)

    # Gate results deliberately do NOT go to quality_runs: the leaderboard builds
    # a row for every model+profile it finds there, so 64 combos would become 64
    # phantom rows with nothing but a quality score. The sweep snapshot already
    # shows them; promote a winner and score that profile to get a real row.

    # --- main loop ---

    def _run(self) -> None:  # noqa: C901
        self.status = "running"
        cluster = get_cluster(self.cluster_id)
        base = base_profile_config(self.family, self.base_profile)
        if cluster is None:
            self.status, self.error = "error", f"cluster {self.cluster_id} not found"
            self.persist()
            return
        if base is None:
            self.status, self.error = "error", f"profile {self.base_profile} not found"
            self.persist()
            return
        if not self.combos:
            self.status, self.error = "error", "empty grid"
            self.persist()
            return
        if len(self.combos) > MAX_COMBOS:
            self.status = "error"
            self.error = f"{len(self.combos)} combinations exceeds the {MAX_COMBOS} cap"
            self.persist()
            return

        try:
            accepted = _resolve_accepted(self.family)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            self.status, self.error = "error", f"model metadata unreadable: {exc}"
            self.persist()
            return
        model_alias = str(accepted.get("alias") or accepted.get("family") or self.family)

        for index, combo in enumerate(self.combos):
            if self._cancel.is_set():
                break
            cfg = {**base, **combo}
            findings = lint_profile(cfg)
            blocking = [f for f in findings if f["level"] == "error"]
            if blocking:
                # A combination the linter calls dead would be measured as "no
                # difference" and silently pollute the ranking. Skip it, loudly.
                self.results.append(
                    {
                        "index": index,
                        "combo": combo,
                        "status": "skipped",
                        "error": "; ".join(f["message"] for f in blocking),
                        "lint": findings,
                    }
                )
                self.persist()
                continue

            entry: dict[str, Any] = {
                "index": index,
                "combo": combo,
                "status": "ok",
                "lint": findings,
            }
            try:
                write_scratch_profile(self.family, self.scratch_profile, cfg)
                launch = dict(accepted)
                launch["profile"] = self.scratch_profile
                reload_started = time.perf_counter()
                active_runners.start(cluster, launch)
                entry["reload_s"] = round(time.perf_counter() - reload_started, 1)
                result = self._measure(cluster, model_alias)
                entry.update(result)
                label = combo_label(self.base_profile, combo)
                self._record(cluster, model_alias, label, result)
                if self.quality_gate:
                    from .quality import run_quality

                    quality = run_quality(
                        cluster.port,
                        model_alias,
                        # The sweep's own budget: a reasoning model on 512 tokens
                        # never reaches its answer, and the gate fails everything.
                        max_tokens=self.max_tokens,
                        judge_url=self.judge_url,
                        judge_model=self.judge_model,
                        timeout=self.request_timeout,
                    )
                    entry["quality"] = quality
                    if quality["pass_rate"] < self.min_pass_rate:
                        # Still measured and reported — just not eligible to win.
                        entry["quality_gate"] = "failed"
            except Exception as exc:  # noqa: BLE001 — one bad combo must not end the sweep
                entry["status"] = "error"
                entry["error"] = str(exc)[:500]
                logger.warning("sweep %s combo %s failed: %s", self.id, combo, exc)
            self.results.append(entry)
            self.persist()

        # Put the cluster back on the profile the user actually runs.
        try:
            delete_scratch_profile(self.family, self.scratch_profile)
            restore = dict(accepted)
            restore["profile"] = self.base_profile
            active_runners.start(cluster, restore)
        except Exception as exc:  # noqa: BLE001
            logger.warning("sweep %s could not restore base profile: %s", self.id, exc)
            self.error = f"sweep finished but restoring {self.base_profile} failed: {exc}"

        self.status = "cancelled" if self._cancel.is_set() else "done"
        self.finished_at = time.time()
        self.persist()


_JOBS: dict[str, SweepJob] = {}


def create(**kwargs: Any) -> SweepJob:
    job = SweepJob(**kwargs)
    _JOBS[job.id] = job
    job.start()
    return job


def get(job_id: str) -> SweepJob | None:
    return _JOBS.get(job_id)


def list_jobs() -> list[dict[str, Any]]:
    live = [
        {
            "id": j.id,
            "status": j.status,
            "family": j.family,
            "completed": len(j.results),
            "total": len(j.combos),
            "started_at": j.started_at,
        }
        for j in _JOBS.values()
    ]
    known = {j["id"] for j in live}
    for path in sorted(sweeps_dir().glob("sweep-*.json"), reverse=True):
        if path.stem in known:
            continue
        try:
            data = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        live.append(
            {
                "id": data.get("id", path.stem),
                "status": data.get("status"),
                "family": data.get("family"),
                "completed": data.get("completed"),
                "total": data.get("total"),
                "started_at": data.get("started_at"),
            }
        )
    return sorted(live, key=lambda j: j.get("started_at") or 0, reverse=True)


def load_persisted(job_id: str) -> dict[str, Any] | None:
    path = sweeps_dir() / f"{job_id}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
