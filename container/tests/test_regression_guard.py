"""Post-rebuild regression guard — verdicts and the known-good ratchet."""

import json

import pytest
from backend import regression
from backend.clusters import ClusterDef


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(regression.config, "RUNS_DIR", tmp_path / "runs")
    monkeypatch.setattr(regression.config, "ACCEPTED_DIR", tmp_path / "runs" / "accepted")
    regression.config.ACCEPTED_DIR.mkdir(parents=True)
    (regression.config.ACCEPTED_DIR / "fam.json").write_text(
        json.dumps({"family": "fam", "alias": "fam-model", "model_path": "/models/fam.gguf"})
    )
    cluster = ClusterDef(
        id="c1",
        name="cluster-7900s",
        gpu_pci_ids=["0000:01:00.0"],
        backend="rocm",
        port=8081,
        container_name="local-llm-runner-cluster-c1",
    )
    monkeypatch.setattr(regression, "list_clusters", lambda: [cluster])
    monkeypatch.setattr(
        regression,
        "list_active",
        lambda: [
            {"cluster_id": "c1", "family": "fam", "profile": "balanced", "model": "fam-model"}
        ],
    )
    monkeypatch.setattr(regression, "read_active", lambda _cid: {"warnings": []})
    monkeypatch.setattr(regression.active_runners, "start", lambda _c, _meta: None)
    return tmp_path


def _measure(tps):
    return lambda port, model: {"decode_tps": tps, "prompt_tps": 900.0}


@pytest.mark.usefixtures("env")
def test_first_run_records_a_baseline(monkeypatch):
    monkeypatch.setattr(regression, "_measure_cluster", _measure(40.0))
    report = regression.run_guard("abc123")
    assert report["clusters"][0]["verdict"] == "baseline"
    assert report["regressions"] == []
    assert regression.load_baselines()["c1:fam:balanced"]["decode_tps"] == 40.0


@pytest.mark.usefixtures("env")
def test_within_threshold_is_ok(monkeypatch):
    monkeypatch.setattr(regression, "_measure_cluster", _measure(40.0))
    regression.run_guard("abc123")
    monkeypatch.setattr(regression, "_measure_cluster", _measure(39.0))  # -2.5%
    report = regression.run_guard("def456")
    assert report["clusters"][0]["verdict"] == "ok"
    assert report["regressions"] == []


@pytest.mark.usefixtures("env")
def test_regression_is_flagged_and_baseline_not_moved(monkeypatch):
    monkeypatch.setattr(regression, "_measure_cluster", _measure(40.0))
    regression.run_guard("abc123")
    monkeypatch.setattr(regression, "_measure_cluster", _measure(30.0))  # -25%
    report = regression.run_guard("def456")

    entry = report["clusters"][0]
    assert entry["verdict"] == "regressed"
    assert entry["delta_pct"] == -25.0
    assert len(report["regressions"]) == 1
    # Known-good must not ratchet down to the slow number.
    assert regression.load_baselines()["c1:fam:balanced"]["decode_tps"] == 40.0
    assert regression.load_baselines()["c1:fam:balanced"]["commit"] == "abc123"


@pytest.mark.usefixtures("env")
def test_improvement_moves_the_baseline_up(monkeypatch):
    monkeypatch.setattr(regression, "_measure_cluster", _measure(40.0))
    regression.run_guard("abc123")
    monkeypatch.setattr(regression, "_measure_cluster", _measure(60.0))
    report = regression.run_guard("def456")
    assert report["clusters"][0]["verdict"] == "improved"
    assert regression.load_baselines()["c1:fam:balanced"]["decode_tps"] == 60.0


@pytest.mark.usefixtures("env")
def test_measurement_failure_does_not_crash_the_guard(monkeypatch):
    def boom(port, model):
        raise RuntimeError("runner never came up")

    monkeypatch.setattr(regression, "_measure_cluster", boom)
    report = regression.run_guard("abc123")
    entry = report["clusters"][0]
    assert entry["verdict"] == "unmeasured"
    assert "never came up" in entry["error"]
    assert regression.load_baselines() == {}


@pytest.mark.usefixtures("env")
def test_accept_blesses_a_regression_deliberately(monkeypatch):
    monkeypatch.setattr(regression, "_measure_cluster", _measure(40.0))
    regression.run_guard("abc123")
    monkeypatch.setattr(regression, "_measure_cluster", _measure(30.0))
    regression.run_guard("def456")

    assert regression.accept_current_as_baseline() == {"updated": 1}
    assert regression.load_baselines()["c1:fam:balanced"]["decode_tps"] == 30.0


def test_baselines_are_keyed_per_cluster_model_and_profile():
    assert regression.baseline_key("c1", "fam", "balanced") != regression.baseline_key(
        "c1", "fam", "rccl"
    )
