"""Log tail reader and SSE stream generator for the project-owned runner."""

import asyncio
import http.client
import socket
import time
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


LOG_SOURCES = {
    "runner": "local-llm-runner",
    "mgmt": "local-llm-mgmt",
}


def _container_name(source: str) -> str:
    return LOG_SOURCES.get(source, LOG_SOURCES["runner"])


def _docker_logs_tail(lines: int, container: str = "local-llm-runner") -> list[str]:
    """Read recent logs from a project container via Docker socket."""
    if not config.DOCKER_SOCKET.exists():
        return []
    conn = _UnixHTTPConnection(config.DOCKER_SOCKET)
    try:
        path = f"/containers/{quote(container)}/logs?stdout=1&stderr=1&tail={lines}&timestamps=0"
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


def read_log_tail(lines: int = 100, source: str = "runner") -> list[str]:
    """Read last N log lines from the selected project container."""
    all_lines = _docker_logs_tail(lines, _container_name(source))
    return all_lines[-lines:] if len(all_lines) > lines else all_lines


async def stream_log_tail(
    disconnect: asyncio.Event,
    source: str = "runner",
    container: str | None = None,
    skip_existing: bool = False,
):
    """SSE generator: stream Docker logs via follow API."""
    container = container or _container_name(source)
    if not config.DOCKER_SOCKET.exists():
        return

    tail_param = f"tail=0&since={int(time.time())}" if skip_existing else "tail=50"
    loop = asyncio.get_running_loop()
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.setblocking(False)

    try:
        await loop.sock_connect(sock, str(config.DOCKER_SOCKET))
        path = f"/containers/{quote(container)}/logs?stdout=1&stderr=1&follow=1&{tail_param}"
        await loop.sock_sendall(sock, f"GET {path} HTTP/1.0\r\nHost: localhost\r\n\r\n".encode())

        buf = b""
        while b"\r\n\r\n" not in buf:
            if disconnect.is_set():
                return
            try:
                chunk = await asyncio.wait_for(loop.sock_recv(sock, 4096), timeout=5.0)
            except asyncio.TimeoutError:
                return
            if not chunk:
                return
            buf += chunk
        _, buf = buf.split(b"\r\n\r\n", 1)

        while not disconnect.is_set():
            while len(buf) >= 8 and buf[0] in (0, 1, 2):
                size = int.from_bytes(buf[4:8], "big")
                if len(buf) < 8 + size:
                    break
                frame = buf[8 : 8 + size].decode("utf-8", errors="replace")
                buf = buf[8 + size :]
                for line in frame.splitlines():
                    if '"GET /logs HTTP/1.1"' not in line:
                        yield f"data: {line}\n\n"

            try:
                chunk = await asyncio.wait_for(loop.sock_recv(sock, 4096), timeout=1.0)
                if not chunk:
                    return
                buf += chunk
            except asyncio.TimeoutError:
                continue
    finally:
        sock.close()
