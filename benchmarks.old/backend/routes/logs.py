"""Log streaming routes."""

import asyncio

from fastapi import APIRouter, Query, Request
from sse_starlette.sse import EventSourceResponse

from ..clusters import list_active as list_active_clusters
from ..log_stream import _docker_logs_tail, stream_log_tail

router = APIRouter(prefix="/api/logs", tags=["logs"])

_MGMT_CONTAINER = "local-llm-mgmt"


def _runner_container(cluster_id: str | None) -> str:
    """Resolve the container name for the runner source."""
    try:
        active = list_active_clusters()
    except OSError:
        return "local-llm-runner"
    if not active:
        return "local-llm-runner"  # graceful fallback; will 404 on docker
    if cluster_id:
        entry = next((a for a in active if a.get("cluster_id") == cluster_id), None)
        if entry:
            return str(entry.get("container", active[0].get("container", "local-llm-runner")))
    return str(active[0].get("container", "local-llm-runner"))


def _container_for(source: str, cluster_id: str | None) -> str:
    if source == "mgmt":
        return _MGMT_CONTAINER
    if source == "router":
        return "local-llm-router"
    return _runner_container(cluster_id)


@router.get("")
async def get_logs(
    lines: int = Query(default=100, ge=1, le=10000),
    source: str = Query(default="runner", pattern="^(runner|mgmt|router)$"),
    cluster_id: str | None = Query(default=None),
    cluster: str | None = Query(default=None, description="Filter router logs to cluster name"),
):
    container = _container_for(source, cluster_id)
    raw = _docker_logs_tail(lines, container)
    if cluster and source == "router":
        raw = [ln for ln in raw if f"[{cluster}]" in ln]
    return {"lines": raw[-lines:] if len(raw) > lines else raw}


@router.get("/stream")
async def stream_logs(
    request: Request,
    no_history: bool = Query(default=False),
    source: str = Query(default="runner", pattern="^(runner|mgmt|router)$"),
    cluster_id: str | None = Query(default=None),
    cluster: str | None = Query(default=None, description="Filter router logs to cluster name"),
):
    """SSE stream of selected project container logs."""
    container = _container_for(source, cluster_id)

    def _passes(line: str) -> bool:
        if not cluster or source != "router":
            return True
        return f"[{cluster}]" in line

    async def event_generator():
        if not no_history:
            for line in _docker_logs_tail(50, container):
                if _passes(line):
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
            async for sse_chunk in stream_log_tail(
                disconnect, container=container, skip_existing=True
            ):
                data = sse_chunk.removeprefix("data: ").removesuffix("\n\n")
                if _passes(data):
                    yield {"event": "log", "data": data}
        finally:
            disconnect.set()
            task.cancel()

    return EventSourceResponse(event_generator())
