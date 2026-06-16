"""Tests for switch endpoint (now returns 501 — use clusters instead)."""

import json
import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture
def temp_state(tmp_path, monkeypatch):
    accepted = tmp_path / "accepted"
    accepted.mkdir(parents=True)
    model_file = tmp_path / "models--Test--Qwen" / "snapshots" / "abc" / "qwen.gguf"
    model_file.parent.mkdir(parents=True)
    model_file.write_text("fake")

    model_data = {
        "family": "qwen",
        "alias": "qwen3.6-27b-q6",
        "model_name": "Qwen3.6 27B Heretic Q6_K",
        "profile": "reliable",
        "context": 131072,
        "backend": "rocm",
        "reasoning": False,
        "repo": "Test/Qwen",
        "hf_repo": "Test/Qwen",
        "hf_file": "qwen.gguf",
        "config": {"ctx": 131072, "batch": 4096, "ubatch": 256, "ngl": 999},
    }
    (accepted / "qwen.json").write_text(json.dumps(model_data, indent=2))

    import backend.config as cfg

    monkeypatch.setattr(cfg, "RUNS_DIR", tmp_path)
    monkeypatch.setattr(cfg, "ACCEPTED_DIR", accepted)
    monkeypatch.setattr(cfg, "LLAMA_CPP_DIR", tmp_path)
    monkeypatch.setattr(cfg, "MODELS_CACHE_DIR", tmp_path)
    return tmp_path


@pytest.mark.asyncio
async def test_switch_returns_501_directing_to_clusters(temp_state):
    """POST /api/models/switch is deprecated; clusters are used instead."""
    _ = temp_state
    from backend.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/models/switch",
            json={"family": "qwen", "profile": "reliable"},
        )

    assert response.status_code == 501
    assert "cluster" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_switch_unknown_family_still_501(temp_state):
    """Even unknown families return 501 now (not 404) — switch is removed."""
    _ = temp_state
    from backend.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/models/switch",
            json={"family": "nonexistent", "profile": "reliable"},
        )

    assert response.status_code == 501
