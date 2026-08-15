"""Coding agents — browser-accessible agent frontends, one port each."""

import os

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

router = APIRouter(prefix="/api/agents", tags=["agents"])

# The agent paths only exist on the Caddy vhost, but mgmt serves the same UI on
# :3100, where the cards' root-relative links 404. Redirect them across rather
# than making the links absolute -- Cloudflare proxies only a fixed port list,
# so a host:port link would hang over the tunnel.
redirect_router = APIRouter(include_in_schema=False)

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
        "name": "OpenCode v1",
        "description": "Agentic coding TUI with session history and sub-agents.",
        "port_env": "AGENT_OPENCODE_PORT",
        "default_port": 3002,
        "url_env": "AGENT_OPENCODE_URL",
        "default_url": "/opencode/",
        "auth": "via Cloudflare Access",
    },
    {
        "id": "opencode2",
        "name": "OpenCode 2 (beta)",
        "description": "OpenCode 2 prerelease, alongside v1 with its own sessions and login.",
        "port_env": "AGENT_OPENCODE2_PORT",
        "default_port": 3009,
        "url_env": "AGENT_OPENCODE2_URL",
        "default_url": "/opencode2/",
        "auth": "via Cloudflare Access",
    },
]


async def _redirect_to_proxy(request: Request):
    port = os.environ.get("PUBLIC_HTTP_PORT", "3001")
    target = f"//{request.url.hostname}:{port}{request.url.path}"
    if request.url.query:
        target = f"{target}?{request.url.query}"
    return RedirectResponse(target, status_code=307)


for _a in _AGENTS:
    _base = os.environ.get(_a["url_env"], _a["default_url"])
    # Only root-relative paths live on the Caddy vhost; an absolute URL already
    # points somewhere reachable and needs no redirect.
    if _base.startswith("/") and not _base.startswith("//"):
        _stripped = _base.rstrip("/")
        redirect_router.add_api_route(_stripped, _redirect_to_proxy, methods=["GET"])
        redirect_router.add_api_route(
            f"{_stripped}/{{rest:path}}", _redirect_to_proxy, methods=["GET"]
        )


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
