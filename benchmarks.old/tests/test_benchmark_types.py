"""Test benchmark type endpoints."""

from importlib import import_module
from pathlib import Path

from backend import config
from backend.main import app
from fastapi.testclient import TestClient

benchmark = import_module("backend.routes.benchmark")


def test_list_benchmark_types(tmp_path: Path, monkeypatch):
    """Test that benchmark types are listed correctly."""
    monkeypatch.setattr(config, "RUNS_DIR", tmp_path)
    benchmark._store.cache_clear()

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
    monkeypatch.setattr(config, "RUNS_DIR", tmp_path)
    benchmark._store.cache_clear()

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
