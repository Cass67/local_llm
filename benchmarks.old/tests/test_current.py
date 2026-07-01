"""Tests for current model endpoint (cluster-based active runner state)."""

import pytest
from httpx import ASGITransport, AsyncClient
from unittest.mock import patch


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
async def test_current_model_returns_active_cluster_state(temp_state):
    _ = temp_state
    from backend.main import app

    active = [
        {
            "cluster_id": "abc1",
            "cluster_name": "dual-amd",
            "model": "qwen3.6-27b-q6",
            "family": "qwen",
            "profile": "reliable",
            "backend": "rocm",
            "port": 8080,
        }
    ]
    with (
        patch("backend.routes.switch.active_runners.list_active", return_value=active),
        patch("backend.routes.switch._native_process_on_runner_port", return_value=False),
    ):
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
    assert "qwen3.6-27b-q6" in data["llama_server"]["running"]
    assert len(data["instances"]) == 1


@pytest.mark.asyncio
async def test_current_model_when_nothing_running(temp_state):
    _ = temp_state
    from backend.main import app

    with (
        patch("backend.routes.switch.active_runners.list_active", return_value=[]),
        patch("backend.routes.switch._native_process_on_runner_port", return_value=False),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/models/current")

    assert response.status_code == 200
    data = response.json()
    assert data["running"] is False
    assert data["alias"] == "none"
    assert data["instances"] == []


@pytest.mark.asyncio
async def test_current_model_multiple_instances(temp_state):
    _ = temp_state
    from backend.main import app

    active = [
        {
            "cluster_id": "c1",
            "model": "qwen",
            "family": "qwen",
            "profile": "reliable",
            "backend": "rocm",
            "port": 8080,
        },
        {
            "cluster_id": "c2",
            "model": "llama",
            "family": "llama",
            "profile": "balanced",
            "backend": "vulkan",
            "port": 8081,
        },
    ]
    with (
        patch("backend.routes.switch.active_runners.list_active", return_value=active),
        patch("backend.routes.switch._native_process_on_runner_port", return_value=False),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/models/current")

    assert response.status_code == 200
    data = response.json()
    assert data["running"] is True
    assert len(data["instances"]) == 2
    running_models = data["llama_server"]["running"]
    assert "qwen" in running_models
    assert "llama" in running_models
