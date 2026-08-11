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
        "url_env": "AGENT_PI_URL",
        "default_url": "/pi/",
        "auth": "via Cloudflare Access",
    },
    {
        "id": "opencode",
        "name": "OpenCode",
        "description": "Agentic coding TUI with session history and sub-agents.",
        "port_env": "AGENT_OPENCODE_PORT",
        "default_port": 3002,
        "url_env": "AGENT_OPENCODE_URL",
        "default_url": "/opencode/",
        "auth": "via Cloudflare Access",
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
                # Absolute or root-relative URL. Set this when the agent is
                # reachable somewhere other than <this host>:<port> -- notably
                # through the cloudflared tunnel, which does not proxy arbitrary
                # ports, so a host:port link hangs from outside the LAN.
                "url": os.environ.get(a["url_env"], a["default_url"]),
                "auth": a["auth"],
            }
            for a in _AGENTS
        ],
    }
