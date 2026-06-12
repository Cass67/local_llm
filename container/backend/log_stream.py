"""Log tail reader and SSE stream generator for the project-owned runner."""

import asyncio
import http.client
import socket
from pathlib import Path
from urllib.parse import quote

from . import config


def _filter_log_noise(lines: list[str]) -> list[str]:
    """Remove log lines caused by log viewers polling runtime endpoints."""
    return [line for line in lines if '"GET /logs HTTP/1.1"' not in line]


class _UnixHTTPConnection(http.client.HTTPConnection):
    def __init__(self, socket_path: Path):
        super().__init__("localhost")
        self.socket_path = socket_path

    def connect(self) -> None:
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect(str(self.socket_path))


def _decode_docker_log_bytes(content: bytes) -> str:
    """Decode Docker log bytes, including stdcopy multiplex headers."""
    chunks: list[bytes] = []
    index = 0
    while index + 8 <= len(content) and content[index] in (0, 1, 2):
        size = int.from_bytes(content[index + 4 : index + 8], "big")
        start = index + 8
        end = start + size
        if size < 0 or end > len(content):
            break
        chunks.append(content[start:end])
        index = end
    if chunks and index == len(content):
        return b"".join(chunks).decode("utf-8", errors="replace")
    return content.decode("utf-8", errors="replace")


def _docker_logs_tail(lines: int) -> list[str]:
    """Read recent logs from local-llm-runner via Docker socket."""
    if not config.DOCKER_SOCKET.exists():
        return []
    conn = _UnixHTTPConnection(config.DOCKER_SOCKET)
    try:
        path = (
            f"/containers/{quote('local-llm-runner')}/logs"
            f"?stdout=1&stderr=1&tail={lines}&timestamps=0"
        )
        conn.request("GET", path)
        response = conn.getresponse()
        content = response.read()
        if response.status >= 400:
            return []
    except OSError:
        return []
    finally:
        conn.close()
    text = _decode_docker_log_bytes(content)
    return _filter_log_noise(text.splitlines())


def read_log_tail(lines: int = 100) -> list[str]:
    """Read last N project runner log lines."""
    all_lines = _docker_logs_tail(lines)
    return all_lines[-lines:] if len(all_lines) > lines else all_lines


async def stream_log_tail(disconnect: asyncio.Event, poll_interval: float = 1.0):
    """SSE generator: poll project runner Docker logs."""
    sent = 0
    while not disconnect.is_set():
        lines = await asyncio.to_thread(_docker_logs_tail, 200)
        for line in lines[sent:]:
            yield f"data: {line}\n\n"
        sent = len(lines)
        await asyncio.sleep(poll_interval)
