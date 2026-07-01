"""Tests for models endpoint."""

import json

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture
def temp_state(tmp_path, monkeypatch):
    """Set up temp state dir with accepted metadata."""
    accepted = tmp_path / "accepted"
    accepted.mkdir(parents=True)

    model_data = {
        "family": "qwen",
        "alias": "qwen3.6-27b-q6",
        "model_name": "Qwen3.6 27B Heretic Q6_K",
        "profile": "reliable",
        "context": 131072,
        "backend": "rocm",
        "config": {
            "quant": "Q6_K",
            "batch": 4096,
            "ubatch": 256,
            "ngl": 999,
            "visible_devices": "0,1",
            "split_mode": "tensor",
            "tensor_split": "1,1",
        },
    }
    (accepted / "qwen.json").write_text(json.dumps(model_data, indent=2))

    import backend.config as cfg

    monkeypatch.setattr(cfg, "RUNS_DIR", tmp_path)
    monkeypatch.setattr(cfg, "ACCEPTED_DIR", accepted)
    return tmp_path


@pytest.mark.asyncio
async def test_list_models_returns_accepted_models(temp_state):
    from backend.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/models")
    assert response.status_code == 200
    data = response.json()
    assert len(data["models"]) == 1
    model = data["models"][0]
    assert model["family"] == "qwen"
    assert model["alias"] == "qwen3.6-27b-q6"
    assert model["backend"] == "rocm"
    assert model["config"]["quant"] == "Q6_K"


@pytest.mark.asyncio
async def test_list_models_empty_returns_empty_list(tmp_path, monkeypatch):
    accepted = tmp_path / "accepted"
    accepted.mkdir(parents=True)

    import backend.config as cfg

    monkeypatch.setattr(cfg, "RUNS_DIR", tmp_path)
    monkeypatch.setattr(cfg, "ACCEPTED_DIR", accepted)

    from backend.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/models")
    assert response.status_code == 200
    data = response.json()
    assert data["models"] == []
