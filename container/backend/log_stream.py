"""Log tail reader and SSE stream generator."""

import asyncio
import json
import urllib.error
import urllib.request

from . import config

LOG_FILE = config.LLAMA_CPP_DIR / "model.log"


def _filter_log_noise(lines: list[str]) -> list[str]:
    """Remove log lines caused by this log viewer polling llama-swap."""
    return [line for line in lines if '"GET /logs HTTP/1.1"' not in line]


def _read_llama_swap_logs() -> list[str]:
    """Read logs from the active llama-swap runtime."""
    try:
        with urllib.request.urlopen(f"{config.LLAMA_SWAP_URL}/logs", timeout=5) as response:
            content = response.read().decode("utf-8", errors="replace")
    except (OSError, urllib.error.URLError):
        return []
    return _filter_log_noise(content.splitlines())


def _read_legacy_log_file() -> list[str]:
    """Read legacy host llama-server model.log."""
    log_path = config.LLAMA_CPP_DIR / "model.log"
    if not log_path.exists() or log_path.is_symlink():
        return []
    try:
        content = log_path.read_text()
    except OSError:
        return []
    return content.splitlines()


def read_log_tail(lines: int = 100) -> list[str]:
    """Read last N runtime log lines."""
    all_lines = _read_llama_swap_logs() or _read_legacy_log_file()
    return all_lines[-lines:] if len(all_lines) > lines else all_lines


def _extract_llama_swap_event_lines(data_line: str) -> list[str]:
    """Extract log lines from a llama-swap /api/events data payload."""
    try:
        event = json.loads(data_line)
    except json.JSONDecodeError:
        return []
    if not isinstance(event, dict) or event.get("type") != "logData":
        return []
    raw_data = event.get("data")
    if not isinstance(raw_data, str):
        return []
    try:
        payload = json.loads(raw_data)
    except json.JSONDecodeError:
        return []
    log_data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(log_data, str):
        return []
    return _filter_log_noise(log_data.splitlines())


async def stream_log_tail(disconnect: asyncio.Event):
    """SSE generator: stream active runtime logs from llama-swap events."""
    try:
        response = await asyncio.to_thread(
            urllib.request.urlopen,
            f"{config.LLAMA_SWAP_URL}/api/events",
            timeout=30,
        )
    except (OSError, urllib.error.URLError):
        yield "event: error\ndata: cannot read llama-swap events\n\n"
        return

    try:
        with response:
            while not disconnect.is_set():
                raw_line = await asyncio.to_thread(response.readline)
                if not raw_line:
                    break
                line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
                if not line.startswith("data:"):
                    continue
                for log_line in _extract_llama_swap_event_lines(line.removeprefix("data:")):
                    yield f"data: {log_line}\n\n"
    except (OSError, urllib.error.URLError):
        yield "event: error\ndata: cannot read llama-swap events\n\n"
