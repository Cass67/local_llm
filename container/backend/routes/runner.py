"""Proxy for runner container health and metadata."""

import httpx
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from .. import active_runners, config

router = APIRouter(prefix="/api/runner", tags=["runner"])


def _runner_base() -> str:
    """Health-check whichever cluster is actually running, not the legacy port."""
    active = active_runners.list_active()
    if active:
        port = active[0].get("port")
        if isinstance(port, int):
            return f"http://127.0.0.1:{port}"
    return config.RUNNER_URL.removesuffix("/v1")


@router.get("/health")
async def runner_health():
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{_runner_base()}/health")
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPError:
        return JSONResponse({"error": "runner unavailable"}, status_code=503)
