"""Tests for runner-owned log streaming."""

import asyncio
import socket as _socket
import struct
from unittest.mock import patch

import pytest
from backend.log_stream import _decode_docker_log_bytes, read_log_tail, stream_log_tail


def test_decode_docker_log_bytes_strips_multiplex_headers():
    raw = b"\x02\x00\x00\x00\x00\x00\x00\x0crunner line\n"

    assert _decode_docker_log_bytes(raw) == "runner line\n"


def test_read_log_tail_reads_local_runner_docker_logs_not_legacy_runtime(tmp_path, monkeypatch):
    import backend.config as cfg

    legacy = tmp_path / "model.log"
    legacy.write_text("old bind failure\n")
    monkeypatch.setattr(cfg, "LLAMA_CPP_DIR", tmp_path)

    with patch(
        "backend.log_stream._docker_logs_tail",
        return_value=["runner model loaded", "server is listening"],
    ):
        assert read_log_tail(10) == ["runner model loaded", "server is listening"]


def _make_frame(text: str) -> bytes:
    data = text.encode("utf-8")
    return bytes([1, 0, 0, 0]) + struct.pack(">I", len(data)) + data


async def _collect_via_socketpair(frames: bytes) -> list[str]:
    server, client = _socket.socketpair(_socket.AF_UNIX, _socket.SOCK_STREAM)
    server.sendall(b"HTTP/1.0 200 OK\r\n\r\n" + frames)
    server.close()

    disconnect = asyncio.Event()
    chunks: list[str] = []

    with patch("backend.log_stream.config.DOCKER_SOCKET") as mock_path:
        mock_path.exists.return_value = True
        with patch("socket.socket", return_value=client):
            loop = asyncio.get_running_loop()
            saved = (loop.sock_connect, loop.sock_sendall)

            loop.sock_connect = lambda _sock, _address: None  # type: ignore[assignment]
            loop.sock_sendall = lambda _sock, _data: None  # type: ignore[assignment]
            try:
                async for chunk in stream_log_tail(disconnect):
                    chunks.append(chunk)
            finally:
                loop.sock_connect, loop.sock_sendall = saved
                client.close()
    return chunks


@pytest.mark.asyncio
async def test_stream_log_tail_streams_runner_logs_without_legacy_runtime_error():
    chunks = await _collect_via_socketpair(_make_frame("runner model loaded\n"))
    assert chunks == ["data: runner model loaded\n\n"]
    assert "llama-swap" not in "".join(chunks)
