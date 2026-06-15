"""Tests for Pi models.json endpoint."""

import json
import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture
def temp_state(tmp_path, monkeypatch):
    accepted = tmp_path / "accepted"
    accepted.mkdir(parents=True)

    model_data = {
        "family": "qwen",
        "alias": "qwen3.6-27b-q6",
        "model_name": "Qwen3.6 27B Heretic Q6_K",
        "profile": "reliable",
        "context": 131072,
        "backend": "rocm",
        "reasoning": True,
    }
    (accepted / "qwen.json").write_text(json.dumps(model_data, indent=2))

    import backend.config as cfg

    monkeypatch.setattr(cfg, "RUNS_DIR", tmp_path)
    monkeypatch.setattr(cfg, "ACCEPTED_DIR", accepted)
    monkeypatch.setattr(cfg, "LLAMA_CPP_DIR", tmp_path)
    return tmp_path


@pytest.mark.asyncio
async def test_pi_models_json_endpoint(temp_state):
    assert temp_state.exists()
    from backend.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://ubt26:3100") as client:
        response = await client.get("/api/pi/models")

    assert response.status_code == 200
    data = response.json()
    assert "providers" in data
    assert "ubt26-llamacpp" in data["providers"]
    provider = data["providers"]["ubt26-llamacpp"]
    assert provider["baseUrl"] == "http://ubt26:3100/v1"
    assert len(provider["models"]) >= 1
    model = provider["models"][0]
    assert model["id"] == "qwen3.6-27b-q6"
    assert model["reasoning"] is True
    assert model["context"] == 131072
    assert model["contextWindow"] == 131072
