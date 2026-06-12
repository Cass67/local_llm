"""Runtime stats endpoint."""

import json

from fastapi import APIRouter

from .. import config

router = APIRouter(prefix="/api", tags=["stats"])


@router.get("/stats")
async def stats():
    path = config.RUNS_DIR / "latest-metrics.json"
    if not path.exists() or path.is_symlink():
        return {}
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}
