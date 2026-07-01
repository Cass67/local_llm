"""Tests for project-owned OpenAI-compatible /v1/models endpoint."""

import pytest
from httpx import ASGITransport, AsyncClient
from unittest.mock import patch


@pytest.fixture
def temp_state(tmp_path, monkeypatch):
    import backend.config as cfg

    accepted = tmp_path / "accepted"
    accepted.mkdir(parents=True)
    monkeypatch.setattr(cfg, "ACCEPTED_DIR", accepted)
    monkeypatch.setattr(cfg, "RUNS_DIR", tmp_path)
    return tmp_path


@pytest.mark.asyncio
async def test_v1_models_lists_only_running_instances(temp_state):
    _ = temp_state
    from backend.main import app

    active = [
        {"cluster_id": "c1", "model": "qwen-q6", "backend": "rocm", "port": 8080},
        {"cluster_id": "c2", "model": "llama-q4", "backend": "vulkan", "port": 8081},
    ]
    with patch("backend.routes.openai.active_runners.list_active", return_value=active):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/v1/models")

    assert response.status_code == 200
    data = response.json()
    assert data["object"] == "list"
    ids = [m["id"] for m in data["data"]]
    assert "qwen-q6" in ids
    assert "llama-q4" in ids


@pytest.mark.asyncio
async def test_v1_models_empty_when_nothing_running(temp_state):
    _ = temp_state
    from backend.main import app

    with patch("backend.routes.openai.active_runners.list_active", return_value=[]):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/v1/models")

    assert response.status_code == 200
    assert response.json()["data"] == []
