"""Tests for logs endpoint."""

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture
def temp_log_dir(tmp_path, monkeypatch):
    log_file = tmp_path / "model.log"
    log_file.write_text("llama-server started\nmodel loaded\n")
    import backend.config as cfg

    monkeypatch.setattr(cfg, "LLAMA_CPP_DIR", tmp_path)
    return tmp_path


@pytest.mark.asyncio
async def test_logs_endpoint_returns_recent_lines(temp_log_dir):
    from backend.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/logs?lines=50")

    assert response.status_code == 200
    data = response.json()
    assert "lines" in data
    assert len(data["lines"]) == 2
    assert "model loaded" in data["lines"][1]


@pytest.mark.asyncio
async def test_logs_no_log_file_returns_empty(tmp_path, monkeypatch):
    import backend.config as cfg

    monkeypatch.setattr(cfg, "LLAMA_CPP_DIR", tmp_path)

    from backend.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/logs?lines=50")

    assert response.status_code == 200
    data = response.json()
    assert data["lines"] == []
