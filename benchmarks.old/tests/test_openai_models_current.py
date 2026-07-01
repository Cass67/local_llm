"""Tests for OpenAI /v1/models reflects active runners."""

import pytest
from httpx import ASGITransport, AsyncClient
from unittest.mock import patch


@pytest.mark.asyncio
async def test_v1_models_lists_active_runners_in_order(tmp_path, monkeypatch):
    import backend.config as cfg

    monkeypatch.setattr(cfg, "RUNS_DIR", tmp_path)
    monkeypatch.setattr(cfg, "ACCEPTED_DIR", tmp_path / "accepted")

    active = [
        {"cluster_id": "c1", "model": "qwopus", "backend": "rocm", "port": 8080},
        {"cluster_id": "c2", "model": "gemma", "backend": "vulkan", "port": 8081},
    ]
    from backend.main import app

    with patch("backend.routes.openai.active_runners.list_active", return_value=active):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/v1/models")

    assert response.status_code == 200
    ids = [m["id"] for m in response.json()["data"]]
    assert ids == ["qwopus", "gemma"]
