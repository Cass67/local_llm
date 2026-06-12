"""Log tail reader and SSE stream generator."""

import asyncio
from . import config

LOG_FILE = config.LLAMA_CPP_DIR / "model.log"


def read_log_tail(lines: int = 100) -> list[str]:
    """Read last N lines from model.log."""
    log_path = config.LLAMA_CPP_DIR / "model.log"
    if not log_path.exists() or log_path.is_symlink():
        return []
    try:
        content = log_path.read_text()
    except OSError:
        return []
    all_lines = content.splitlines()
    return all_lines[-lines:] if len(all_lines) > lines else all_lines


async def stream_log_tail(disconnect: asyncio.Event):
    """SSE generator: tail -f model.log."""
    log_path = config.LLAMA_CPP_DIR / "model.log"
    if not log_path.exists():
        yield "event: error\ndata: log file not found\n\n"
        return

    try:
        with open(log_path) as f:
            f.seek(0, 2)  # End of file
            while not disconnect.is_set():
                line = f.readline()
                if line:
                    yield f"data: {line.rstrip()}\n\n"
                else:
                    await asyncio.sleep(0.5)
    except OSError:
        yield "event: error\ndata: cannot read log file\n\n"
