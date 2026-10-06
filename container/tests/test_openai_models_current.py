"""Tests for OpenAI /v1/models reflects active runners."""

from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient


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
    # "router" is the always-present sentinel, listed before any real runner.
    assert ids == ["router", "qwopus", "gemma"]


@pytest.mark.asyncio
async def test_v1_models_lists_external_runner_and_routes_to_it(tmp_path, monkeypatch):
    import json

    import backend.config as cfg
    from backend import active_runners
    from backend.routes.chat import _resolve_runner_url

    monkeypatch.setattr(cfg, "RUNS_DIR", tmp_path)
    monkeypatch.setattr(cfg, "ACCEPTED_DIR", tmp_path / "accepted")
    monkeypatch.setattr(cfg, "STATE_DIR", tmp_path)
    (tmp_path / "external_runners.json").write_text(
        json.dumps(
            [{"model": "strata", "url": "http://127.0.0.1:3300/v1/", "context_window": 131072}]
        )
    )
    from backend.main import app

    with (
        patch("backend.routes.openai.active_runners.list_active", return_value=[]),
        patch("backend.routes.openai.list_desired", return_value=[]),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            data = (await client.get("/v1/models")).json()["data"]

    assert [m["id"] for m in data] == ["router", "strata"]
    assert data[0]["context_window"] == data[1]["context_window"] == 131072
    with patch.object(active_runners, "list_active", return_value=[]):
        assert _resolve_runner_url(b'{"model": "strata"}') == "http://127.0.0.1:3300/v1"
        assert _resolve_runner_url(b'{"model": "router"}') == "http://127.0.0.1:3300/v1"
