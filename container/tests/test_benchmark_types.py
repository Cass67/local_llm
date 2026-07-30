"""Test benchmark type endpoints."""

from importlib import import_module
from pathlib import Path

from backend import config
from backend.main import app
from fastapi.testclient import TestClient

benchmark = import_module("backend.routes.benchmark")
terminal_bench = import_module("backend.benchmarks.terminal_bench")
swe_bench = import_module("backend.benchmarks.swe_bench")


def _isolate_state(tmp_path: Path, monkeypatch):
    """Redirect every run-output path at tmp_path.

    The benchmark modules derive _RUNS_DIR from _STATE_DIR at import time, so
    patching config.RUNS_DIR alone leaves them writing to the real /state.
    """
    monkeypatch.setattr(config, "RUNS_DIR", tmp_path)
    monkeypatch.setattr(terminal_bench, "_RUNS_DIR", tmp_path / "terminal_bench")
    monkeypatch.setattr(swe_bench, "_RUNS_DIR", tmp_path / "swe_bench")
    monkeypatch.setitem(benchmark._LOG_DIRS, "terminal-bench", tmp_path / "terminal_bench")
    monkeypatch.setitem(benchmark._LOG_DIRS, "swe-bench", tmp_path / "swe_bench")
    benchmark._store.cache_clear()


def test_list_benchmark_types(tmp_path: Path, monkeypatch):
    """Test that benchmark types are listed correctly."""
    _isolate_state(tmp_path, monkeypatch)

    client = TestClient(app)
    response = client.get("/api/local-llm/benchmark/types")
    assert response.status_code == 200
    data = response.json()
    assert "types" in data
    assert len(data["types"]) >= 2  # terminal-bench and swe-bench

    type_names = [t["name"] for t in data["types"]]
    assert "terminal-bench" in type_names
    assert "swe-bench" in type_names


def test_run_benchmark_type(tmp_path: Path, monkeypatch):
    """Test running a benchmark by type."""
    _isolate_state(tmp_path, monkeypatch)

    client = TestClient(app)

    # Create an endpoint
    endpoint = client.post(
        "/api/local-llm/benchmark/endpoints",
        json={"name": "test", "base_url": "http://localhost:8080/v1"},
    ).json()

    # Run a terminal-bench benchmark
    response = client.post(
        "/api/local-llm/benchmark/runs/terminal-bench",
        json={
            "endpoint_id": endpoint["id"],
            "model": "test-model",
            "prompt_text": "ls -la",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] in ("ok", "error")  # depends on whether command executed
    assert data["benchmark_type"] == "terminal-bench"

    # Verify it was stored
    summary = client.get("/api/local-llm/benchmark/summary?benchmark_type=terminal-bench").json()
    assert summary["total_runs"] == 1
