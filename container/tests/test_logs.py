"""Tests for logs endpoint."""

import asyncio
import json
from io import BytesIO
from unittest.mock import patch
import urllib.request

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
    _ = temp_log_dir
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


@pytest.mark.asyncio
async def test_logs_endpoint_prefers_llama_swap_logs(monkeypatch):
    import backend.config as cfg

    monkeypatch.setattr(cfg, "LLAMA_SWAP_URL", "http://llama-swap")

    class Response(BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, _exc_type, _exc, _tb):
            return None

    log_body = (
        "old line\n"
        '[INFO] Request 127.0.0.1 "GET /logs HTTP/1.1" 200 1 "Python-urllib/3.12" 1us\n'
        "live llama-swap line\n"
    ).encode()
    with patch.object(
        urllib.request,
        "urlopen",
        return_value=Response(log_body),
    ) as mock_urlopen:
        from backend.main import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/logs?lines=1")

    assert response.status_code == 200
    assert response.json()["lines"] == ["live llama-swap line"]
    mock_urlopen.assert_called_once_with("http://llama-swap/logs", timeout=5)


@pytest.mark.asyncio
async def test_stream_log_tail_reads_llama_swap_events(monkeypatch):
    import backend.config as cfg
    from backend.log_stream import stream_log_tail

    monkeypatch.setattr(cfg, "LLAMA_SWAP_URL", "http://llama-swap")
    event_payload = {
        "type": "logData",
        "data": json.dumps(
            {
                "data": 'first line\n[INFO] Request 127.0.0.1 "GET /logs HTTP/1.1" 200 1 "Python-urllib/3.12" 1us\nsecond line\n',
                "source": "proxy",
            }
        ),
    }
    stream = (f"event:message\ndata:{json.dumps(event_payload)}\n\n").encode()

    class Response(BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, _exc_type, _exc, _tb):
            return None

    with patch.object(urllib.request, "urlopen", return_value=Response(stream)) as mock_urlopen:
        disconnect = asyncio.Event()
        chunks = []
        async for chunk in stream_log_tail(disconnect):
            chunks.append(chunk)

    assert chunks == ["data: first line\n\n", "data: second line\n\n"]
    mock_urlopen.assert_called_once_with("http://llama-swap/api/events", timeout=30)
