"""Coding agents — browser-accessible agent frontends, one port each."""

import os

from fastapi import APIRouter

router = APIRouter(prefix="/api/agents", tags=["agents"])

_AGENTS = [
    {
        "id": "pi",
        "name": "pi",
        "description": "Terminal coding agent (read/bash/edit/write) in a browser terminal.",
        "port_env": "AGENT_PI_PORT",
        "default_port": 3006,
        "auth": "basic (user: pi)",
    },
    {
        "id": "opencode",
        "name": "OpenCode",
        "description": "Agentic coding with a native web UI and session history.",
        "port_env": "AGENT_OPENCODE_PORT",
        "default_port": 3002,
        "auth": "basic (user: opencode)",
    },
]


@router.get("")
async def list_agents():
    return {
        "workdir": os.environ.get("AGENTS_REPO_DIR", "/home/cass/git"),
        "agents": [
            {
                "id": a["id"],
                "name": a["name"],
                "description": a["description"],
                "port": int(os.environ.get(a["port_env"], a["default_port"])),
                "auth": a["auth"],
            }
            for a in _AGENTS
        ],
    }
