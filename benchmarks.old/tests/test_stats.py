"""Tests for runtime stats endpoint."""

import json

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.mark.asyncio
async def test_stats_returns_latest_metrics(tmp_path, monkeypatch):
    import backend.config as cfg

    monkeypatch.setattr(cfg, "RUNS_DIR", tmp_path)
    (tmp_path / "latest-metrics.json").write_text(
        json.dumps({"model": "qwopus", "predicted_per_second": 42.5})
    )
    from backend.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/stats")

    assert response.status_code == 200
    assert response.json() == {"model": "qwopus", "predicted_per_second": 42.5}


@pytest.mark.asyncio
async def test_stats_returns_empty_when_no_metrics(tmp_path, monkeypatch):
    import backend.config as cfg

    monkeypatch.setattr(cfg, "RUNS_DIR", tmp_path)
    from backend.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/stats")

    assert response.status_code == 200
    assert response.json() == {}
