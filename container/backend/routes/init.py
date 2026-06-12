"""Target initialization endpoint."""
import json
import re
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from .. import config

router = APIRouter(prefix="/api", tags=["init"])

SAFE_TARGET_PATTERN = re.compile(r"^local$|^remote:[A-Za-z0-9_.:-]+$")


class InitRequest(BaseModel):
    target: str


@router.post("/init")
async def init_target(req: InitRequest):
    """Set the management target (local or remote:<host>)."""
    if not SAFE_TARGET_PATTERN.match(req.target):
        raise HTTPException(400, f"invalid target: {req.target}")

    config.RUNS_DIR.mkdir(parents=True, exist_ok=True)
    config_file = config.RUNS_DIR / "config.json"
    config_file.write_text(json.dumps({
        "target": req.target,
    }, indent=2) + "\n")

    return {"status": "ok", "target": req.target}
