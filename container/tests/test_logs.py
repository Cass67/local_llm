"""Tests for logs endpoint."""

import asyncio
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.mark.asyncio
async def test_logs_endpoint_returns_recent_runner_lines():
    with patch(
        "backend.log_stream._docker_logs_tail",
        return_value=["llama-server started", "model loaded"],
    ):
        from backend.main import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/logs?lines=50")

    assert response.status_code == 200
    data = response.json()
    assert data["lines"] == ["llama-server started", "model loaded"]


@pytest.mark.asyncio
async def test_logs_no_runner_logs_returns_empty():
    with patch("backend.log_stream._docker_logs_tail", return_value=[]):
        from backend.main import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/logs?lines=50")

    assert response.status_code == 200
    data = response.json()
    assert data["lines"] == []


@pytest.mark.asyncio
async def test_logs_endpoint_does_not_call_legacy_runtime():
    with (
        patch("backend.log_stream._docker_logs_tail", return_value=["runner line"]),
        patch("urllib.request.urlopen") as urlopen,
    ):
        from backend.main import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/logs?lines=1")

    assert response.status_code == 200
    assert response.json()["lines"] == ["runner line"]
    urlopen.assert_not_called()


@pytest.mark.asyncio
async def test_stream_log_tail_streams_runner_logs_without_legacy_runtime_events():
    from backend.log_stream import stream_log_tail

    with patch(
        "backend.log_stream._docker_logs_tail",
        side_effect=[["first line"], ["first line", "second line"]],
    ):
        disconnect = asyncio.Event()
        chunks = []
        async for chunk in stream_log_tail(disconnect, poll_interval=0.01):
            chunks.append(chunk)
            if len(chunks) == 2:
                disconnect.set()
                break

    assert chunks == ["data: first line\n\n", "data: second line\n\n"]
    assert "llama-swap" not in "".join(chunks)
