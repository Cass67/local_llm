"""Proxy for runner container health and metadata."""

import httpx
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from .. import config

router = APIRouter(prefix="/api/runner", tags=["runner"])

_RUNNER_BASE = config.RUNNER_URL.removesuffix("/v1")


@router.get("/health")
async def runner_health():
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{_RUNNER_BASE}/health")
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPError:
        return JSONResponse({"error": "runner unavailable"}, status_code=503)
