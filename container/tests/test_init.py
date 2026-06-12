"""Tests for init endpoint."""

import json
import pytest
from httpx import ASGITransport, AsyncClient
from backend.main import app


@pytest.mark.asyncio
async def test_init_sets_target(tmp_path):
    import backend.config as cfg

    old_runs = cfg.RUNS_DIR
    cfg.RUNS_DIR = tmp_path
    cfg.ACCEPTED_DIR = tmp_path / "accepted"

    try:
        (tmp_path / "accepted").mkdir(parents=True, exist_ok=True)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/api/init", json={"target": "local"})

        assert response.status_code == 200
        config_file = tmp_path / "config.json"
        assert config_file.exists()
        data = json.loads(config_file.read_text())
        assert data["target"] == "local"
    finally:
        cfg.RUNS_DIR = old_runs
        cfg.ACCEPTED_DIR = old_runs / "accepted"


@pytest.mark.asyncio
async def test_init_rejects_invalid_target():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/init", json={"target": "bad;target"})

    assert response.status_code == 400
