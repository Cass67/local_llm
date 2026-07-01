"""Router config management — read/write router_rules.json and proxy router health."""

import http.client
import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from .. import config

router = APIRouter(prefix="/api/router", tags=["router"])

_REQUIRED_FIELDS = {"backend_url"}


def _load() -> dict:
    if not config.ROUTER_CONFIG.exists():
        return {
            "backend_url": f"http://127.0.0.1:{config.LLAMA_SERVER_PORT}",
            "default_model": None,
            "health_check_interval_s": 10,
            "enabled": True,
            "rules": [],
        }
    try:
        return json.loads(config.ROUTER_CONFIG.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail=f"corrupt router config: {exc}") from exc


def _validate(cfg: dict) -> None:
    missing = _REQUIRED_FIELDS - cfg.keys()
    if missing:
        raise HTTPException(status_code=422, detail=f"missing required fields: {missing}")
    if not isinstance(cfg.get("rules", []), list):
        raise HTTPException(status_code=422, detail="rules must be a list")
    for rule in cfg.get("rules", []):
        keywords = rule.get("keywords", [])
        signals = rule.get("signals", [])
        if not isinstance(keywords, list):
            raise HTTPException(status_code=422, detail="each rule needs a keywords list")
        if not keywords and not signals:
            raise HTTPException(
                status_code=422, detail="each rule needs at least one keyword or signal"
            )
        if not rule.get("cluster") and not rule.get("model"):
            raise HTTPException(status_code=422, detail="each rule needs cluster or model")


@router.get("/config")
async def get_router_config():
    return _load()


@router.put("/config")
async def put_router_config(body: dict):
    _validate(body)
    config.ROUTER_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    config.ROUTER_CONFIG.write_text(json.dumps(body, indent=2))
    return {"status": "saved"}


@router.get("/health")
async def get_router_health():
    try:
        conn = http.client.HTTPConnection("127.0.0.1", config.ROUTER_PORT, timeout=3)
        conn.request("GET", "/health")
        resp = conn.getresponse()
        data = json.loads(resp.read())
        conn.close()
        return {"running": True, **data}
    except OSError:
        return JSONResponse({"running": False, "detail": "router not reachable"}, status_code=200)
    except Exception as exc:
        return JSONResponse({"running": False, "detail": str(exc)}, status_code=200)
