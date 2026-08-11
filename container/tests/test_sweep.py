"""Profile autotuner — grid expansion, ranking, and the full measure loop."""

import json

import pytest
from backend import sweep
from backend.clusters import ClusterDef


def test_expand_grid_is_cartesian_and_ordered():
    combos = sweep.expand_grid({"ubatch": [256, 512], "batch": [2048, 4096]})
    assert combos == [
        {"batch": 2048, "ubatch": 256},
        {"batch": 2048, "ubatch": 512},
        {"batch": 4096, "ubatch": 256},
        {"batch": 4096, "ubatch": 512},
    ]


def test_expand_grid_rejects_empty_axes():
    assert sweep.expand_grid({}) == []
    assert sweep.expand_grid({"ubatch": []}) == []


def test_single_axis_grid():
    assert sweep.expand_grid({"ubatch": [256]}) == [{"ubatch": 256}]


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Isolated state dir with one family, one profile, and one accepted model."""
    monkeypatch.setattr(sweep.config, "RUNS_DIR", tmp_path / "runs")
    monkeypatch.setattr(sweep.config, "ACCEPTED_DIR", tmp_path / "runs" / "accepted")
    monkeypatch.setattr(sweep.config, "PROFILES_CONFIG", tmp_path / "profiles.json")
    sweep.config.ACCEPTED_DIR.mkdir(parents=True)
    (sweep.config.ACCEPTED_DIR / "fam.json").write_text(
        json.dumps({"family": "fam", "alias": "fam-model", "model_path": "/models/fam.gguf"})
    )
    sweep.config.PROFILES_CONFIG.write_text(
        json.dumps(
            {
                "families": {
                    "fam": {
                        "default": "balanced",
                        "profiles": {"balanced": {"ngl": 999, "batch": 4096, "ubatch": 256}},
                    }
                }
            }
        )
    )
    return tmp_path


@pytest.fixture
def fake_cluster(monkeypatch):
    cluster = ClusterDef(
        id="c1",
        name="c1",
        gpu_pci_ids=["0000:01:00.0"],
        backend="rocm",
        port=8081,
        container_name="local-llm-runner-cluster-c1",
    )
    monkeypatch.setattr(sweep, "get_cluster", lambda cid: cluster if cid == "c1" else None)
    return cluster


def _run_to_completion(job, timeout=10.0):
    job._thread.join(timeout)
    assert not job._thread.is_alive(), "sweep thread did not finish"


@pytest.mark.usefixtures("env", "fake_cluster")
def test_sweep_measures_every_combo_and_ranks_best(monkeypatch):
    launched = []
    monkeypatch.setattr(
        sweep.active_runners, "start", lambda _c, meta: launched.append(meta["profile"])
    )
    # Larger ubatch is faster here, so the sweep must pick 512.
    tps = {256: 20.0, 512: 35.0}

    def fake_chat(_port, _model, _prompt, _system, _max_tokens, _timeout):
        cfg = sweep.base_profile_config("fam", "balanced-sweep") or {}
        return {
            "decode_tps": tps[cfg.get("ubatch", 256)],
            "prompt_tps": 900.0,
            "completion_tokens": 128,
            "wall_s": 1.0,
            "text": "hello",
        }

    monkeypatch.setattr(sweep, "_chat_once", fake_chat)

    job = sweep.SweepJob(
        family="fam",
        cluster_id="c1",
        base_profile="balanced",
        grid={"ubatch": [256, 512]},
        prompt_text="hi",
        repeats=1,
        warmup=0,
    )
    job.start()
    _run_to_completion(job)

    assert job.status == "done"
    assert [r["status"] for r in job.results] == ["ok", "ok"]
    assert job.best()["combo"] == {"ubatch": 512}
    assert job.best()["decode_tps"] == 35.0
    # base profile restored on the cluster at the end
    assert launched[-1] == "balanced"
    # scratch profile cleaned up
    assert sweep.base_profile_config("fam", "balanced-sweep") is None


@pytest.mark.usefixtures("env", "fake_cluster")
def test_sweep_skips_combos_the_linter_calls_dead(monkeypatch):
    monkeypatch.setattr(sweep.active_runners, "start", lambda _c, _meta: None)
    monkeypatch.setattr(
        sweep,
        "_chat_once",
        lambda *_a, **_k: {"decode_tps": 10.0, "completion_tokens": 8, "wall_s": 1.0, "text": ""},
    )
    job = sweep.SweepJob(
        family="fam",
        cluster_id="c1",
        base_profile="balanced",
        # ubatch 8192 > batch 4096 is invalid; the linter must catch it before a reload.
        grid={"ubatch": [512, 8192]},
        prompt_text="hi",
        repeats=1,
        warmup=0,
    )
    job.start()
    _run_to_completion(job)

    by_combo = {r["combo"]["ubatch"]: r for r in job.results}
    assert by_combo[512]["status"] == "ok"
    assert by_combo[8192]["status"] == "skipped"
    assert "exceeds batch" in by_combo[8192]["error"]


@pytest.mark.usefixtures("env", "fake_cluster")
def test_failed_combo_does_not_abort_the_sweep(monkeypatch):
    monkeypatch.setattr(sweep.active_runners, "start", lambda _c, _meta: None)
    calls = {"n": 0}

    def flaky(*_a, **_k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("runner OOM")
        return {"decode_tps": 12.0, "completion_tokens": 8, "wall_s": 1.0, "text": ""}

    monkeypatch.setattr(sweep, "_chat_once", flaky)
    job = sweep.SweepJob(
        family="fam",
        cluster_id="c1",
        base_profile="balanced",
        grid={"ubatch": [256, 512]},
        prompt_text="hi",
        repeats=1,
        warmup=0,
    )
    job.start()
    _run_to_completion(job)

    assert [r["status"] for r in job.results] == ["error", "ok"]
    assert "OOM" in job.results[0]["error"]
    assert job.best()["combo"] == {"ubatch": 512}


@pytest.mark.usefixtures("env", "fake_cluster")
def test_results_persist_to_disk(monkeypatch):
    monkeypatch.setattr(sweep.active_runners, "start", lambda _c, _meta: None)
    monkeypatch.setattr(
        sweep,
        "_chat_once",
        lambda *_a, **_k: {"decode_tps": 30.0, "completion_tokens": 8, "wall_s": 1.0, "text": ""},
    )
    job = sweep.SweepJob(
        family="fam",
        cluster_id="c1",
        base_profile="balanced",
        grid={"ubatch": [256]},
        prompt_text="hi",
        repeats=1,
        warmup=0,
    )
    job.start()
    _run_to_completion(job)

    saved = sweep.load_persisted(job.id)
    assert saved["status"] == "done"
    assert saved["best"]["decode_tps"] == 30.0


@pytest.mark.usefixtures("env")
def test_missing_cluster_errors_cleanly(monkeypatch):
    monkeypatch.setattr(sweep, "get_cluster", lambda _cid: None)
    job = sweep.SweepJob(
        family="fam",
        cluster_id="nope",
        base_profile="balanced",
        grid={"ubatch": [256]},
        prompt_text="hi",
    )
    job.start()
    _run_to_completion(job)
    assert job.status == "error"
    assert "not found" in job.error


@pytest.mark.usefixtures("env", "fake_cluster")
def test_tps_per_watt_objective_ranks_on_efficiency(monkeypatch):
    monkeypatch.setattr(sweep.active_runners, "start", lambda _c, _meta: None)
    monkeypatch.setattr(
        sweep,
        "_chat_once",
        lambda *_a, **_k: {"decode_tps": 20.0, "completion_tokens": 8, "wall_s": 1.0, "text": ""},
    )
    # 256 draws half the power for the same throughput → wins on efficiency.
    watts = {256: 200.0, 512: 400.0}

    class FakeSampler:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return None

        def result(self):
            cfg = sweep.base_profile_config("fam", "balanced-sweep") or {}
            return {"psu_avg_w": watts[cfg.get("ubatch", 256)], "psu_peak_w": None, "samples": 4}

    monkeypatch.setattr(sweep, "PowerSampler", FakeSampler)
    job = sweep.SweepJob(
        family="fam",
        cluster_id="c1",
        base_profile="balanced",
        grid={"ubatch": [256, 512]},
        prompt_text="hi",
        repeats=1,
        warmup=0,
        objective="tps_per_watt",
    )
    job.start()
    _run_to_completion(job)
    assert job.best()["combo"] == {"ubatch": 256}
    assert job.best()["tps_per_watt"] == 0.1
