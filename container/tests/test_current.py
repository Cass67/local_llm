"""Tests for current model endpoint."""

import json

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture
def temp_state(tmp_path, monkeypatch):
    import backend.config as cfg

    accepted = tmp_path / "accepted"
    accepted.mkdir(parents=True)
    monkeypatch.setattr(cfg, "RUNS_DIR", tmp_path)
    monkeypatch.setattr(cfg, "ACCEPTED_DIR", accepted)
    monkeypatch.setattr(cfg, "LLAMA_CPP_DIR", tmp_path)
    return tmp_path


@pytest.mark.asyncio
async def test_current_model_returns_project_runner_state(temp_state, monkeypatch):
    monkeypatch.setattr(
        "backend.routes.switch._runner_api_model_ids",
        lambda: {"qwen3.6-27b-q6"},
    )
    from backend.main import app

    (temp_state / "current-runner.json").write_text(
        json.dumps(
            {
                "model": "qwen3.6-27b-q6",
                "family": "qwen",
                "profile": "reliable",
                "backend": "rocm",
            }
        )
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/models/current")

    assert response.status_code == 200
    data = response.json()
    assert data["family"] == "qwen"
    assert data["alias"] == "qwen3.6-27b-q6"
    assert data["profile"] == "reliable"
    assert data["running"] is True
    assert data["llama_server"]["status"] == "local-llm-runner"


@pytest.mark.asyncio
async def test_current_model_marks_saved_runner_state_not_running_when_runner_api_is_down(
    temp_state, monkeypatch
):
    import backend.config as cfg

    monkeypatch.setattr(cfg, "RUNNER_URL", "http://127.0.0.1:9/v1")
    (temp_state / "current-runner.json").write_text(
        json.dumps(
            {
                "model": "qwen3.6-27b-q6",
                "family": "qwen",
                "profile": "reliable",
                "backend": "rocm",
            }
        )
    )

    from backend.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/models/current")

    assert response.status_code == 200
    data = response.json()
    assert data["family"] == "qwen"
    assert data["alias"] == "qwen3.6-27b-q6"
    assert data["profile"] == "reliable"
    assert data["running"] is False
    assert data["llama_server"]["running"] == []


@pytest.mark.asyncio
async def test_current_model_falls_back_to_selection_when_runner_not_started(temp_state):
    from backend.main import app

    (temp_state / "current-selection.json").write_text(
        json.dumps(
            {
                "model": "qwen3.6-27b-q6",
                "family": "qwen",
                "profile": "reliable",
                "backend": "rocm",
            }
        )
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/models/current")

    assert response.status_code == 200
    data = response.json()
    assert data["family"] == "qwen"
    assert data["alias"] == "qwen3.6-27b-q6"
    assert data["profile"] == "reliable"
    assert data["running"] is False
    assert data["llama_server"]["running"] == []


@pytest.mark.asyncio
async def test_current_model_when_no_selection(temp_state):
    from backend.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/models/current")

    assert response.status_code == 200
    data = response.json()
    assert data["running"] is False
    assert data["family"] == "unknown"
    assert data["alias"] == "unknown"
