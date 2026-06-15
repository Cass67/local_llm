"""Tests for logs endpoint."""

import asyncio
import socket as _socket
import struct
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
async def test_logs_endpoint_can_return_mgmt_lines():
    with patch(
        "backend.log_stream._docker_logs_tail",
        return_value=["api benchmark loaded"],
    ) as logs_tail:
        from backend.main import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/logs?source=mgmt&lines=25")

    assert response.status_code == 200
    data = response.json()
    assert data["lines"] == ["api benchmark loaded"]
    logs_tail.assert_called_once_with(25, "local-llm-mgmt")


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


def _make_docker_frame(text: str, stream_type: int = 1) -> bytes:
    data = text.encode("utf-8")
    return bytes([stream_type, 0, 0, 0]) + struct.pack(">I", len(data)) + data


def _fake_docker_response(*texts: str) -> bytes:
    frames = b"".join(_make_docker_frame(t) for t in texts)
    return b"HTTP/1.0 200 OK\r\n\r\n" + frames


@pytest.mark.asyncio
async def test_stream_log_tail_yields_lines():
    from backend.log_stream import stream_log_tail

    server, client = _socket.socketpair(_socket.AF_UNIX, _socket.SOCK_STREAM)
    server.sendall(_fake_docker_response("first line\n", "second line\n"))
    server.close()

    disconnect = asyncio.Event()
    chunks = []

    with patch("backend.log_stream.config.DOCKER_SOCKET") as mock_path:
        mock_path.exists.return_value = True
        with patch("socket.socket", return_value=client):
            loop = asyncio.get_event_loop()
            saved = (loop.sock_connect, loop.sock_sendall)

            loop.sock_connect = lambda _sock, _address: None  # type: ignore[assignment]
            loop.sock_sendall = lambda _sock, _data: None  # type: ignore[assignment]
            try:
                async for chunk in stream_log_tail(disconnect, source="runner"):
                    chunks.append(chunk)
            finally:
                loop.sock_connect, loop.sock_sendall = saved
                client.close()

    assert chunks == ["data: first line\n\n", "data: second line\n\n"]


@pytest.mark.asyncio
async def test_stream_log_tail_skip_existing_yields_only_new():
    from backend.log_stream import stream_log_tail

    server, client = _socket.socketpair(_socket.AF_UNIX, _socket.SOCK_STREAM)
    server.sendall(_fake_docker_response("new line\n"))
    server.close()

    disconnect = asyncio.Event()
    chunks = []

    with patch("backend.log_stream.config.DOCKER_SOCKET") as mock_path:
        mock_path.exists.return_value = True
        with patch("socket.socket", return_value=client):
            loop = asyncio.get_event_loop()
            saved = (loop.sock_connect, loop.sock_sendall)

            loop.sock_connect = lambda _sock, _address: None  # type: ignore[assignment]
            loop.sock_sendall = lambda _sock, _data: None  # type: ignore[assignment]
            try:
                async for chunk in stream_log_tail(disconnect, source="runner", skip_existing=True):
                    chunks.append(chunk)
            finally:
                loop.sock_connect, loop.sock_sendall = saved
                client.close()

    assert chunks == ["data: new line\n\n"]
