import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "container"))

from backend.benchmark_store import BenchmarkStore  # noqa: E402


def _run(store, **overrides):
    values = {
        "endpoint_id": 1,
        "endpoint_name": "Cluster: 7900s",
        "endpoint_base_url": "http://127.0.0.1:8081",
        "model": "qwopus-27b",
        "prompt_text": "hi",
        "response_text": "hello",
        "output_chars": 5,
        "output_words": 1,
        "status": "ok",
    }
    values.update(overrides)
    return store.create_run(**values)


def test_leaderboard_joins_speed_quality_and_agentic(tmp_path):
    store = BenchmarkStore(tmp_path / "b.sqlite3")
    _run(store, profile="rccl", throughput_tps=30.0, latency_ms=1000.0, tps_per_watt=0.05)
    _run(store, profile="rccl", throughput_tps=40.0, latency_ms=2000.0, tps_per_watt=0.07)
    _run(store, model="muse-30b", profile="balanced", throughput_tps=55.0, latency_ms=900.0)
    _run(
        store,
        benchmark_type="terminal-bench",
        profile="rccl",
        response_text="3/10 tasks resolved (1 errored)",
    )
    store.create_quality_run(
        model="qwopus-27b",
        profile="rccl",
        cluster_id="7900s",
        passed=4,
        total=5,
        pass_rate=0.8,
        judge_mean=4.2,
    )

    rows = store.leaderboard()["rows"]
    assert [r["model"] for r in rows] == ["muse-30b", "qwopus-27b"]  # fastest first

    qwopus = rows[1]
    assert qwopus["runs"] == 2
    assert qwopus["best_tps"] == 40.0
    assert qwopus["avg_tps"] == 35.0
    assert qwopus["best_tps_per_watt"] == 0.07
    assert qwopus["quality_pass_rate"] == 0.8
    assert qwopus["quality_judge_mean"] == 4.2
    assert qwopus["agentic"]["terminal-bench"] == {
        "resolved": 3,
        "total": 10,
        "rate": 0.3,
        "at": qwopus["agentic"]["terminal-bench"]["at"],
    }

    # agentic runs never count as speed samples
    assert rows[0]["runs"] == 1


def test_leaderboard_ignores_failed_and_unparsable_runs(tmp_path):
    store = BenchmarkStore(tmp_path / "b.sqlite3")
    _run(store, throughput_tps=99.0, status="error", error="boom")
    _run(store, benchmark_type="swe-bench", response_text="harness crashed")
    assert store.leaderboard()["rows"] == []
