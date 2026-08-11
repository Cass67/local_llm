import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "container"))

import pytest  # noqa: E402
from backend import bakeoff, measure  # noqa: E402
from backend.benchmark_store import BenchmarkStore  # noqa: E402
from backend.clusters import ClusterDef  # noqa: E402

CLUSTER = ClusterDef(
    id="c1",
    name="7900s",
    gpu_pci_ids=["0000:01:00.0"],
    backend="vulkan",
    port=8081,
    container_name="local-llm-runner-c1",
)


@pytest.fixture
def env(tmp_path, monkeypatch):
    accepted = tmp_path / "accepted"
    accepted.mkdir()
    for family in ("alpha", "beta"):
        (accepted / f"{family}.json").write_text(json.dumps({"family": family, "alias": family}))
    monkeypatch.setattr(bakeoff.config, "ACCEPTED_DIR", accepted)

    started: list[str] = []
    monkeypatch.setattr(
        bakeoff.active_runners,
        "start",
        lambda cluster, meta: started.append(f"{meta['family']}/{meta.get('profile', '')}"),
    )
    monkeypatch.setattr(
        measure,
        "chat_once",
        lambda _port, _model, _prompt, _sys_prompt, _max_tokens, _timeout: {
            "decode_tps": 40.0,
            "completion_tokens": 100,
            "wall_s": 2.5,
            "text": "def lru(): pass",
        },
    )
    monkeypatch.setattr(measure, "PowerSampler", _FakeSampler)
    monkeypatch.setattr(
        bakeoff.quality,
        "run_quality",
        lambda _port, _model, **_kw: {
            "cases": [],
            "passed": 4,
            "total": 5,
            "pass_rate": 0.8,
            "judge_mean": None,
        },
    )
    store = BenchmarkStore(tmp_path / "b.sqlite3")
    return started, store


class _FakeSampler:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def result(self):
        return {"psu_avg_w": 400.0, "psu_peak_w": 500.0, "gpu_avg_w": 300.0}


def _job(total=2):
    return bakeoff.BakeoffJob(id="j1", cluster_id="c1", total=total)


def test_bakeoff_walks_every_entry_and_records_runs(env):
    started, store = env
    job = _job()
    bakeoff.run_bakeoff(
        job,
        CLUSTER,
        [bakeoff.BakeoffEntry("alpha", "rccl"), bakeoff.BakeoffEntry("beta", "")],
        repeats=2,
        store_factory=lambda: store,
    )

    assert job.status == "done"
    assert started == ["alpha/rccl", "beta/"]
    assert [r["model"] for r in job.results] == ["alpha", "beta"]
    assert all(r["runs"] == 2 and r["quality"] == 0.8 for r in job.results)

    rows = store.leaderboard()["rows"]
    assert {r["model"] for r in rows} == {"alpha", "beta"}
    alpha = next(r for r in rows if r["model"] == "alpha")
    # 2 measured runs; the warm-up must not be recorded.
    assert alpha["runs"] == 2
    assert alpha["profile"] == "rccl"
    assert alpha["best_tps"] == 40.0
    assert alpha["quality_pass_rate"] == 0.8
    assert alpha["best_tps_per_watt"] == pytest.approx(0.1)


def test_a_model_that_will_not_load_is_logged_and_skipped(env, monkeypatch):
    started, store = env

    def explode(cluster, meta):
        if meta["family"] == "alpha":
            raise RuntimeError("out of VRAM")
        started.append(meta["family"])

    monkeypatch.setattr(bakeoff.active_runners, "start", explode)
    job = _job()
    bakeoff.run_bakeoff(
        job,
        CLUSTER,
        [bakeoff.BakeoffEntry("alpha"), bakeoff.BakeoffEntry("beta")],
        repeats=1,
        with_quality=False,
        store_factory=lambda: store,
    )

    assert job.status == "done"
    assert started == ["beta"]
    assert job.results[0]["error"].startswith("out of VRAM")
    assert job.results[1]["best_tps"] == 40.0
    assert any("FAILED" in line for line in job.log)


def test_cancel_stops_before_the_next_entry(env):
    started, store = env
    job = _job()
    job.cancelled = True
    bakeoff.run_bakeoff(
        job,
        CLUSTER,
        [bakeoff.BakeoffEntry("alpha")],
        store_factory=lambda: store,
    )
    assert job.status == "cancelled"
    assert started == []
    assert store.leaderboard()["rows"] == []


def test_missing_family_is_reported_not_raised(env):
    _, store = env
    job = _job(total=1)
    bakeoff.run_bakeoff(
        job,
        CLUSTER,
        [bakeoff.BakeoffEntry("nope")],
        with_quality=False,
        store_factory=lambda: store,
    )
    assert job.status == "done"
    assert "not found" in job.results[0]["error"]
