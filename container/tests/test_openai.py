"""Tests for project-owned OpenAI-compatible metadata endpoints."""

import json

from httpx import ASGITransport, AsyncClient
import pytest


@pytest.fixture
def temp_state(tmp_path, monkeypatch):
    accepted = tmp_path / "accepted"
    accepted.mkdir(parents=True)
    (accepted / "qwen.json").write_text(
        json.dumps(
            {
                "family": "qwen",
                "alias": "qwen3.6-27b-q6",
                "model_name": "Qwen3.6 27B Q6",
                "context": 65536,
                "reasoning": False,
                "config": {"backend": "vulkan"},
            }
        )
    )

    import backend.config as cfg

    monkeypatch.setattr(cfg, "ACCEPTED_DIR", accepted)
    monkeypatch.setattr(cfg, "RUNS_DIR", tmp_path)
    return tmp_path


@pytest.mark.asyncio
async def test_v1_models_lists_accepted_models_without_legacy_runtime(temp_state):
    from backend.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/v1/models")

    assert response.status_code == 200
    data = response.json()
    assert data["object"] == "list"
    assert data["data"] == [
        {
            "id": "qwen3.6-27b-q6",
            "object": "model",
            "owned_by": "local_llm",
            "context": 65536,
            "backend": "vulkan",
            "reasoning": False,
        }
    ]
