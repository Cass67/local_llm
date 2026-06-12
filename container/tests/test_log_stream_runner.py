"""Tests for runner-owned log streaming."""

import asyncio
from unittest.mock import patch

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


async def _collect_first_chunk():
    disconnect = asyncio.Event()
    chunks = []
    async for chunk in stream_log_tail(disconnect, poll_interval=0.01):
        chunks.append(chunk)
        disconnect.set()
        break
    return chunks


def test_stream_log_tail_streams_runner_logs_without_legacy_runtime_error():
    with patch(
        "backend.log_stream._docker_logs_tail",
        side_effect=[["runner model loaded"], ["runner model loaded", "ready"]],
    ):
        chunks = asyncio.run(_collect_first_chunk())

    assert chunks == ["data: runner model loaded\n\n"]
    assert "llama-swap" not in "".join(chunks)
