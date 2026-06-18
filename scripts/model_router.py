"""Model router — picks model from keywords, forwards to backend."""

import json
import time
import os
from pathlib import Path

import httpx
from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

# --- config ---

CONFIG_PATH = Path(__file__).parent.parent / "configs" / "router_rules.json"
PORT = int(os.environ.get("ROUTER_PORT", "3200"))

with CONFIG_PATH.open() as f:
    CFG = json.load(f)

BACKEND_URL = CFG["backend_url"].rstrip("/")
DEFAULT_MODEL = CFG.get("default_model")  # None → first available
HEALTH_INTERVAL = CFG.get("health_check_interval_s", 10)
RULES = CFG.get("rules", [])

# --- health cache ---

_healthy_aliases: set[str] = set()
_cluster_to_model: dict[str, str] = {}  # cluster name → current model alias
_last_health_check: float = 0.0


async def _refresh_health() -> None:
    global _healthy_aliases, _cluster_to_model, _last_health_check
    try:
        async with httpx.AsyncClient(timeout=5.0) as c:
            models_resp = await c.get(f"{BACKEND_URL}/v1/models")
            models_resp.raise_for_status()
            _healthy_aliases = {m["id"] for m in models_resp.json().get("data", [])}

            clusters_resp = await c.get(f"{BACKEND_URL}/api/clusters")
            if clusters_resp.status_code == 200:
                clusters = clusters_resp.json().get("clusters", [])
                _cluster_to_model = {
                    c["name"]: c["active"]["model"]
                    for c in clusters
                    if c.get("active") and c["active"].get("running") and c["active"].get("model")
                }
    except Exception as exc:
        print(f"router: health refresh failed: {exc}")
    _last_health_check = time.monotonic()


async def _maybe_refresh() -> None:
    if time.monotonic() - _last_health_check > HEALTH_INTERVAL:
        await _refresh_health()


def _resolve_model(rule_model: str | None, rule_cluster: str | None) -> str | None:
    """Resolve a rule's target to a healthy model alias, or None."""
    if rule_cluster:
        alias = _cluster_to_model.get(rule_cluster)
        if alias and alias in _healthy_aliases:
            return alias
        return None
    if rule_model and rule_model in _healthy_aliases:
        return rule_model
    return None


def _default_model() -> str:
    """Return configured default, or first healthy model if default is unset/unavailable."""
    if DEFAULT_MODEL and DEFAULT_MODEL in _healthy_aliases:
        return DEFAULT_MODEL
    return next(iter(sorted(_healthy_aliases)), "")


def _is_healthy(alias: str) -> bool:
    return alias in _healthy_aliases


# --- routing ---


def _extract_prompt(messages: list[dict]) -> str:
    """Return last message content as prompt text."""
    for msg in reversed(messages):
        content = msg.get("content", "")
        if isinstance(content, str) and content.strip():
            return content.strip().lower()
        if isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    return part["text"].strip().lower()
    return ""


def _route(prompt: str) -> str:
    """First-match-wins keyword routing."""
    for rule in RULES:
        if not any(kw in prompt for kw in rule["keywords"]):
            continue
        chosen = _resolve_model(rule.get("model"), rule.get("cluster"))
        if chosen:
            return chosen
        for fb in rule.get("fallback", []):
            # fallback entries can be model aliases or cluster names
            fb_alias = _cluster_to_model.get(fb, fb)
            if fb_alias in _healthy_aliases:
                return fb_alias
        # primary + fallbacks all down — skip rule, try next
    return _default_model()


# --- proxy ---


def _is_stream(payload: dict) -> bool:
    return bool(payload.get("stream"))


async def _proxy_stream(payload: dict, request: Request) -> StreamingResponse:
    client = httpx.AsyncClient(timeout=300.0)
    stream_ctx = client.stream(
        "POST",
        f"{BACKEND_URL}/v1/chat/completions",
        content=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        upstream = await stream_ctx.__aenter__()
    except httpx.HTTPError:
        await client.aclose()
        return JSONResponse({"detail": "backend unavailable"}, status_code=503)

    if upstream.status_code != 200:
        body_bytes = await upstream.aread()
        await stream_ctx.__aexit__(None, None, None)
        await client.aclose()
        try:
            detail = json.loads(body_bytes).get(
                "error", body_bytes.decode("utf-8", errors="replace")
            )
        except (json.JSONDecodeError, AttributeError):
            detail = body_bytes.decode("utf-8", errors="replace")
        return JSONResponse({"detail": detail}, status_code=upstream.status_code)

    async def stream_upstream():
        try:
            async for raw in upstream.aiter_raw():
                yield raw
        finally:
            await stream_ctx.__aexit__(None, None, None)
            await client.aclose()

    return StreamingResponse(stream_upstream(), media_type="text/event-stream")


async def _proxy_nonstream(payload: dict) -> Response:
    async with httpx.AsyncClient(timeout=300.0) as client:
        upstream = await client.post(
            f"{BACKEND_URL}/v1/chat/completions",
            content=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        media_type=upstream.headers.get("content-type", "application/json"),
    )


# --- app ---

app = FastAPI(title="model-router")
router = APIRouter()


@router.get("/v1/models")
async def v1_models():
    """Passthrough to backend."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as c:
            resp = await c.get(f"{BACKEND_URL}/v1/models")
        return Response(
            content=resp.content,
            status_code=resp.status_code,
            media_type=resp.headers.get("content-type", "application/json"),
        )
    except Exception as exc:
        return JSONResponse({"detail": str(exc)}, status_code=502)


@router.post("/v1/chat/completions")
async def v1_chat_completions(request: Request):
    body = await request.body()
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return JSONResponse({"detail": "invalid JSON"}, status_code=400)

    # Bypass when model already set explicitly
    if not (isinstance(payload.get("model"), str) and payload["model"]):
        await _maybe_refresh()
        prompt = _extract_prompt(payload.get("messages", []))
        chosen = _route(prompt)
        if not chosen:
            return JSONResponse({"detail": "no healthy model available"}, status_code=503)
        payload["model"] = chosen

    if _is_stream(payload):
        return await _proxy_stream(payload, request)
    return await _proxy_nonstream(payload)


@router.get("/health")
async def health():
    await _maybe_refresh()
    return {
        "status": "ok",
        "backend": BACKEND_URL,
        "healthy_models": sorted(_healthy_aliases),
        "cluster_map": _cluster_to_model,
        "default_model": DEFAULT_MODEL or f"(first available: {_default_model() or 'none'})",
    }


app.include_router(router)

if __name__ == "__main__":
    import uvicorn
    import asyncio

    asyncio.run(_refresh_health())
    uvicorn.run(app, host="0.0.0.0", port=PORT)  # nosec B104
