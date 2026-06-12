"""Tests for OpenAI model ordering."""

import json

from httpx import ASGITransport, AsyncClient
import pytest


@pytest.mark.asyncio
async def test_v1_models_lists_current_selection_first(tmp_path, monkeypatch):
    import backend.config as cfg

    accepted = tmp_path / "accepted"
    accepted.mkdir(parents=True)
    for family in ["gemma", "qwopus"]:
        (accepted / f"{family}.json").write_text(
            json.dumps(
                {
                    "family": family,
                    "alias": family,
                    "model_name": family,
                    "profile": "reliable",
                    "backend": "vulkan",
                    "reasoning": False,
                }
            )
        )
    (tmp_path / "current-selection.json").write_text(
        json.dumps({"model": "qwopus", "family": "qwopus"})
    )
    monkeypatch.setattr(cfg, "RUNS_DIR", tmp_path)
    monkeypatch.setattr(cfg, "ACCEPTED_DIR", accepted)

    from backend.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/v1/models")

    assert response.status_code == 200
    ids = [model["id"] for model in response.json()["data"]]
    assert ids == ["qwopus", "gemma"]
