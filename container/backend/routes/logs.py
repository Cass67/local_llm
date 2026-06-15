"""Log streaming routes."""

import asyncio
from fastapi import APIRouter, Request, Query
from sse_starlette.sse import EventSourceResponse
from ..log_stream import read_log_tail, stream_log_tail

router = APIRouter(prefix="/api/logs", tags=["logs"])


@router.get("")
async def get_logs(
    lines: int = Query(default=100, ge=1, le=10000),
    source: str = Query(default="runner", pattern="^(runner|mgmt)$"),
):
    return {"lines": read_log_tail(lines, source)}


@router.get("/stream")
async def stream_logs(
    request: Request,
    no_history: bool = Query(default=False),
    source: str = Query(default="runner", pattern="^(runner|mgmt)$"),
):
    """SSE stream of selected project container logs."""

    async def event_generator():
        # Send buffered history first
        if not no_history:
            for line in read_log_tail(50, source):
                yield {"event": "log", "data": line}

        disconnect = asyncio.Event()

        async def check_disconnect():
            while True:
                if await request.is_disconnected():
                    disconnect.set()
                    break
                await asyncio.sleep(1)

        task = asyncio.create_task(check_disconnect())

        try:
            async for sse_chunk in stream_log_tail(disconnect, source=source, skip_existing=True):
                # Extract data from "data: ...\n\n" format
                data = sse_chunk.removeprefix("data: ").removesuffix("\n\n")
                yield {"event": "log", "data": data}
        finally:
            disconnect.set()
            task.cancel()

    return EventSourceResponse(event_generator())
