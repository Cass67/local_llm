"""Idle unload settings — auto-stop cluster runners after N minutes of inactivity."""

import json
import logging

from fastapi import APIRouter

from .. import config

router = APIRouter(prefix="/api/idle-unload", tags=["idle-unload"])

_CONFIG_PATH = config.STATE_DIR / "idle_unload.json"
_DEFAULTS = {"enabled": False, "timeout_minutes": 10}


def load() -> dict:
    if not _CONFIG_PATH.exists():
        return dict(_DEFAULTS)
    try:
        data = json.loads(_CONFIG_PATH.read_text())
        return {**_DEFAULTS, **data}
    except (OSError, json.JSONDecodeError):
        return dict(_DEFAULTS)


def _save(cfg: dict) -> None:
    _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CONFIG_PATH.write_text(json.dumps(cfg, indent=2) + "\n")


@router.get("")
async def get_config():
    return load()


@router.put("")
async def put_config(body: dict):
    cfg = {
        "enabled": bool(body.get("enabled", _DEFAULTS["enabled"])),
        "timeout_minutes": int(body.get("timeout_minutes", _DEFAULTS["timeout_minutes"])),
    }
    _save(cfg)
    logging.info(
        "idle_unload: %s (timeout=%dm)",
        "enabled" if cfg["enabled"] else "disabled",
        cfg["timeout_minutes"],
    )
    return cfg
