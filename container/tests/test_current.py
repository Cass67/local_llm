"""Tests for current model endpoint."""

import json
import pytest
from unittest.mock import patch
from httpx import ASGITransport, AsyncClient


@pytest.fixture
def temp_state(tmp_path, monkeypatch):
    import backend.config as cfg

    accepted = tmp_path / "accepted"
    launchers = tmp_path / "launchers"
    accepted.mkdir(parents=True)
    launchers.mkdir(parents=True)
    monkeypatch.setattr(cfg, "RUNS_DIR", tmp_path)
    monkeypatch.setattr(cfg, "ACCEPTED_DIR", accepted)
    monkeypatch.setattr(cfg, "LAUNCHERS_DIR", launchers)
    monkeypatch.setattr(cfg, "LLAMA_CPP_DIR", tmp_path)
    return tmp_path


@pytest.mark.asyncio
async def test_current_model_returns_selected_running_model(temp_state):
    from backend.main import app

    (temp_state / "current-selection.json").write_text(json.dumps({
        "model": "qwen3.6-27b-q6",
        "family": "qwen",
        "profile": "reliable",
        "backend": "rocm",
    }))

    with patch("backend.routes.switch.get_llama_swap_running_ids", return_value=["qwen3.6-27b-q6"]):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/models/current")

    assert response.status_code == 200
    data = response.json()
    assert data["family"] == "qwen"
    assert data["alias"] == "qwen3.6-27b-q6"
    assert data["profile"] == "reliable"
    assert data["running"] is True
    assert data["llama_server"]["status"] == "llama-swap"


@pytest.mark.asyncio
async def test_current_model_when_no_selection(temp_state):
    from backend.main import app

    with patch("backend.routes.switch.get_llama_swap_running_ids", return_value=[]):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/models/current")

    assert response.status_code == 200
    data = response.json()
    assert data["running"] is False
    assert data["family"] == "unknown"
    assert data["alias"] == "unknown"
