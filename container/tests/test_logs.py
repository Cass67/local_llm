"""Tests for logs endpoint."""

import socket as _socket
import struct
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient


_NO_ACTIVE = []  # mock return for list_active_clusters in logs route


@pytest.mark.asyncio
async def test_logs_endpoint_returns_recent_runner_lines():
    with (
        patch(
            "backend.routes.logs._docker_logs_tail",
            return_value=["llama-server started", "model loaded"],
        ),
        patch("backend.routes.logs.list_active_clusters", return_value=_NO_ACTIVE),
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
    with (
        patch(
            "backend.routes.logs._docker_logs_tail", return_value=["api benchmark loaded"]
        ) as logs_tail,
        patch("backend.routes.logs.list_active_clusters", return_value=_NO_ACTIVE),
    ):
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
    with (
        patch("backend.routes.logs._docker_logs_tail", return_value=[]),
        patch("backend.routes.logs.list_active_clusters", return_value=_NO_ACTIVE),
    ):
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
        patch("backend.routes.logs._docker_logs_tail", return_value=["runner line"]),
        patch("backend.routes.logs.list_active_clusters", return_value=_NO_ACTIVE),
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
async def test_logs_routes_runner_to_active_cluster_container():
    active = [{"cluster_id": "abc123", "container": "local-llm-runner-cluster-gpu0-abc123"}]
    with (
        patch("backend.routes.logs._docker_logs_tail", return_value=["model loaded"]) as logs_tail,
        patch("backend.routes.logs.list_active_clusters", return_value=active),
    ):
        from backend.main import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/logs?lines=10&cluster_id=abc123")

    assert response.status_code == 200
    logs_tail.assert_called_once_with(10, "local-llm-runner-cluster-gpu0-abc123")


def _make_docker_frame(text: str, stream_type: int = 1) -> bytes:
    data = text.encode("utf-8")
    return bytes([stream_type, 0, 0, 0]) + struct.pack(">I", len(data)) + data


def _fake_docker_response(*texts: str) -> bytes:
    frames = b"".join(_make_docker_frame(t) for t in texts)
    return b"HTTP/1.0 200 OK\r\n\r\n" + frames


async def _noop(*_args, **_kwargs):
    return None


@pytest.mark.asyncio
async def test_stream_log_tail_yields_lines():
    import asyncio
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
            loop.sock_connect = _noop
            loop.sock_sendall = _noop
            try:
                async for chunk in stream_log_tail(disconnect, source="runner"):
                    chunks.append(chunk)
            finally:
                loop.sock_connect, loop.sock_sendall = saved
                client.close()

    assert chunks == ["data: first line\n\n", "data: second line\n\n"]


@pytest.mark.asyncio
async def test_stream_log_tail_skip_existing_yields_only_new():
    import asyncio
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
            loop.sock_connect = _noop
            loop.sock_sendall = _noop
            try:
                async for chunk in stream_log_tail(disconnect, source="runner", skip_existing=True):
                    chunks.append(chunk)
            finally:
                loop.sock_connect, loop.sock_sendall = saved
                client.close()

    assert chunks == ["data: new line\n\n"]
