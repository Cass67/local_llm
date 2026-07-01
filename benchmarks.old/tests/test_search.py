"""Tests for search endpoint."""

import json
from unittest.mock import MagicMock, patch

import pytest
from backend.main import app
from httpx import ASGITransport, AsyncClient


@pytest.mark.asyncio
async def test_search_returns_candidates():
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = json.dumps(
        {
            "candidates": [
                {
                    "repo": "TheBloke/qwen-Q6_K-GGUF",
                    "score": 85,
                    "best_quant": "Q6_K",
                    "best_file": "qwen.Q6_K.gguf",
                },
                {
                    "repo": "TheBloke/qwen-Q4_K_M-GGUF",
                    "score": 72,
                    "best_quant": "Q4_K_M",
                    "best_file": "qwen.Q4_K_M.gguf",
                },
            ]
        }
    )
    mock_result.stderr = ""

    with patch("backend.cli.subprocess.run", return_value=mock_result) as mock_run:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/search", params={"query": "qwen coding gguf"})

    assert response.status_code == 200
    data = response.json()
    assert len(data["candidates"]) == 2
    assert data["candidates"][0]["repo"] == "TheBloke/qwen-Q6_K-GGUF"
    assert data["candidates"][0]["score"] == 85
    mock_run.assert_called_once()
    cmd = mock_run.call_args[0][0]
    assert any("model-discovery" in str(a) for a in cmd)


@pytest.mark.asyncio
async def test_search_no_results():
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = json.dumps({"candidates": []})
    mock_result.stderr = ""

    with patch("backend.cli.subprocess.run", return_value=mock_result):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/search", params={"query": "xyznonexistent"})

    assert response.status_code == 200
    data = response.json()
    assert data["candidates"] == []


@pytest.mark.asyncio
async def test_search_cli_failure():
    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stdout = ""
    mock_result.stderr = "discovery failed: network error"

    with patch("backend.cli.subprocess.run", return_value=mock_result):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/search", params={"query": "test"})

    assert response.status_code == 200
    data = response.json()
    assert data["error"] is not None
    assert "discovery failed" in data["error"].lower()
