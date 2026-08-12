"""Log streaming routes."""

import asyncio

from fastapi import APIRouter, Query, Request
from sse_starlette.sse import EventSourceResponse

from ..clusters import get_cluster
from ..clusters import list_active as list_active_clusters
from ..log_stream import _docker_logs_tail, stream_log_tail

router = APIRouter(prefix="/api/logs", tags=["logs"])

_MGMT_CONTAINER = "local-llm-mgmt"


def _runner_container(cluster_id: str | None) -> str:
    """Resolve the container name for the runner source.

    Prefer the cluster definition: a runner that segfaulted or failed readiness
    leaves an exited container whose logs hold the reason, but it is gone from
    the active list, so resolving through active only would hide exactly the
    logs someone opens this tab to read.
    """
    if cluster_id:
        cluster = get_cluster(cluster_id)
        if cluster:
            return cluster.container_name
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


async def _watch_disconnect(request: Request, disconnect: asyncio.Event) -> None:
    while not await request.is_disconnected():
        await asyncio.sleep(1)
    disconnect.set()


async def _log_events(request: Request, container: str, no_history: bool, passes):
    if not no_history:
        for line in _docker_logs_tail(50, container):
            if passes(line):
                yield {"event": "log", "data": line}

    disconnect = asyncio.Event()
    task = asyncio.create_task(_watch_disconnect(request, disconnect))
    try:
        async for sse_chunk in stream_log_tail(disconnect, container=container, skip_existing=True):
            data = sse_chunk.removeprefix("data: ").removesuffix("\n\n")
            if passes(data):
                yield {"event": "log", "data": data}
        # Docker's follow ends immediately for an exited container. Returning here
        # would make the browser reconnect every 3s and re-dump the same history,
        # so hold the stream open until the client goes away instead.
        await disconnect.wait()
    finally:
        disconnect.set()
        task.cancel()


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

    return EventSourceResponse(_log_events(request, container, no_history, _passes))
