"""Tests for install endpoint."""
import json
import pytest
from unittest.mock import patch, MagicMock
from httpx import ASGITransport, AsyncClient
from backend.main import app


@pytest.mark.asyncio
async def test_install_model_success():
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = json.dumps({
        "status": "installed",
        "family": "qwen-test",
        "alias": "qwen-test-q6",
    })
    mock_result.stderr = ""

    with patch("backend.cli.subprocess.run", return_value=mock_result):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/api/search/install", json={
                "repo": "TheBloke/qwen-Q6_K-GGUF",
                "file": "qwen.Q6_K.gguf",
                "profile": "balanced",
            })

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "installed"


@pytest.mark.asyncio
async def test_install_model_failure():
    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stdout = ""
    mock_result.stderr = "download failed: disk full"

    with patch("backend.cli.subprocess.run", return_value=mock_result):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/api/search/install", json={
                "repo": "TheBloke/qwen-Q6_K-GGUF",
                "file": "qwen.Q6_K.gguf",
                "profile": "balanced",
            })

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "error"
    assert "disk full" in data["detail"]
