"""Model router — picks model from keywords, forwards to backend."""

import json
import re
import time
import os
from pathlib import Path

import httpx
from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

# --- config ---

PORT = int(os.environ.get("ROUTER_PORT", "3200"))

_STATE_CONFIG = (
    Path(os.environ.get("ROUTER_CONFIG", ""))
    or Path(os.environ.get("LOCAL_LLM_STATE_DIR", "/state")) / "router_rules.json"
)
_REPO_CONFIG = Path(__file__).parent.parent / "configs" / "router_rules.json"
_CONFIG_PATH = _STATE_CONFIG if _STATE_CONFIG.exists() else _REPO_CONFIG
_config_mtime: float = 0.0

# Runtime config — reloaded when the file changes
BACKEND_URL = "http://127.0.0.1:3100"
DEFAULT_MODEL: str | None = None
HEALTH_INTERVAL: int = 10
RULES: list[dict] = []
ENABLED: bool = True
CLUSTER_REMAP: dict[str, str] = {}


def _reload_config() -> None:
    global \
        BACKEND_URL, \
        DEFAULT_MODEL, \
        HEALTH_INTERVAL, \
        RULES, \
        ENABLED, \
        CLUSTER_REMAP, \
        _config_mtime, \
        _CONFIG_PATH
    path = _STATE_CONFIG if _STATE_CONFIG.exists() else _REPO_CONFIG
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return
    if path == _CONFIG_PATH and mtime == _config_mtime:
        return
    try:
        cfg = json.loads(path.read_text())
        BACKEND_URL = cfg.get("backend_url", BACKEND_URL).rstrip("/")
        DEFAULT_MODEL = cfg.get("default_model")
        HEALTH_INTERVAL = cfg.get("health_check_interval_s", 10)
        RULES = cfg.get("rules", [])
        ENABLED = cfg.get("enabled", True)
        remap = cfg.get("cluster_remap", {})
        CLUSTER_REMAP = remap if isinstance(remap, dict) else {}
        _CONFIG_PATH = path
        _config_mtime = mtime
    except (OSError, json.JSONDecodeError):
        pass


_reload_config()

# --- health cache ---

_healthy_aliases: set[str] = set()
_cluster_to_model: dict[str, str] = {}  # cluster name → current model alias
_last_health_check: float = 0.0


async def _refresh_health() -> None:
    global _healthy_aliases, _cluster_to_model, _last_health_check
    _reload_config()
    try:
        async with httpx.AsyncClient(timeout=5.0) as c:
            models_resp = await c.get(f"{BACKEND_URL}/v1/models")
            models_resp.raise_for_status()
            _healthy_aliases = {m["id"] for m in models_resp.json().get("data", [])}

            clusters_resp = await c.get(f"{BACKEND_URL}/api/clusters")
            if clusters_resp.status_code == 200:
                clusters = clusters_resp.json().get("clusters", [])
                old_map = _cluster_to_model.copy()
                _cluster_to_model = {
                    c["name"]: c["active"]["model"]
                    for c in clusters
                    if c.get("active") and c["active"].get("running") and c["active"].get("model")
                }
                for name, model in sorted(_cluster_to_model.items()):
                    if old_map.get(name) != model:
                        print(f"router: active [{name}] {model}", flush=True)
    except Exception as exc:
        print(f"router: health refresh failed: {exc}")
    _last_health_check = time.monotonic()


async def _maybe_refresh() -> None:
    if time.monotonic() - _last_health_check > HEALTH_INTERVAL:
        await _refresh_health()


def _remap_cluster(name: str) -> str:
    return str(CLUSTER_REMAP.get(name, name))


def _resolve_model(rule_model: str | None, rule_cluster: str | None) -> str | None:
    """Resolve a rule's target to a healthy model alias, or None."""
    if rule_cluster:
        alias = _cluster_to_model.get(_remap_cluster(rule_cluster))
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
    """Return last user message content for routing — ignore tool/assistant messages."""
    for msg in reversed(messages):
        if msg.get("role") != "user":
            continue
        content = msg.get("content", "")
        if isinstance(content, str) and content.strip():
            return content.strip().lower()
        if isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    return part["text"].strip().lower()
    return ""


def _keyword_in(keyword: str, prompt: str) -> bool:
    if not keyword.strip():
        return False
    if keyword[-1:].isalnum() and keyword[:1].isalnum():
        return re.search(rf"(?<![a-z0-9]){re.escape(keyword)}(?![a-z0-9])", prompt) is not None
    return keyword in prompt


def _route_detail(prompt: str) -> dict:
    """First-match-wins keyword routing with explanation."""
    for rule in RULES:
        matched = next(
            (kw for kw in rule.get("keywords", []) if _keyword_in(str(kw), prompt)), None
        )
        if not matched:
            continue
        raw_cluster = rule.get("cluster")
        remapped_cluster = _remap_cluster(raw_cluster) if raw_cluster else None
        chosen = _resolve_model(rule.get("model"), raw_cluster)
        if chosen:
            return {
                "model": chosen,
                "reason": "rule",
                "rule": rule.get("name"),
                "matched_keyword": matched,
                "cluster": raw_cluster,
                "remapped_cluster": remapped_cluster,
            }
        for fb in rule.get("fallback", []):
            # fallback entries can be model aliases or cluster names
            fb_cluster = _remap_cluster(fb)
            fb_alias = _cluster_to_model.get(fb_cluster, fb)
            if fb_alias in _healthy_aliases:
                return {
                    "model": fb_alias,
                    "reason": "fallback",
                    "rule": rule.get("name"),
                    "matched_keyword": matched,
                    "cluster": raw_cluster,
                    "remapped_cluster": remapped_cluster,
                    "fallback": fb,
                    "remapped_fallback": fb_cluster,
                }
        # primary + fallbacks all down — skip rule, try next
    return {"model": _default_model(), "reason": "default"}


def _route(prompt: str) -> str:
    return str(_route_detail(prompt).get("model") or "")


# --- proxy ---


def _is_stream(payload: dict) -> bool:
    return bool(payload.get("stream"))


async def _proxy_stream(payload: dict, request: Request) -> Response:
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

    # "auto" (and empty) are sentinels meaning "let the router decide"
    _ROUTE_SENTINELS = {"auto", "router", "local-auto", ""}
    model_val = payload.get("model") or ""
    explicit_model = bool(model_val) and model_val not in _ROUTE_SENTINELS

    if ENABLED and not explicit_model:
        await _maybe_refresh()
        prompt = _extract_prompt(payload.get("messages", []))
        chosen = _route(prompt)
        if not chosen:
            return JSONResponse({"detail": "no healthy model available"}, status_code=503)
        payload["model"] = chosen
        cluster = next((k for k, v in _cluster_to_model.items() if v == chosen), "?")
        print(f"router: [{cluster}] {chosen} ← {prompt[:80]!r}", flush=True)
    else:
        model = payload.get("model", "")
        cluster = next((k for k, v in _cluster_to_model.items() if v == model), "client-specified")
        prompt = _extract_prompt(payload.get("messages", []))
        print(f"router: [{cluster}] {model} ← {prompt[:80]!r}", flush=True)

    if _is_stream(payload):
        return await _proxy_stream(payload, request)
    return await _proxy_nonstream(payload)


@router.post("/route/preview")
async def route_preview(request: Request):
    body = await request.body()
    try:
        payload = json.loads(body) if body else {}
    except json.JSONDecodeError:
        payload = {}
    prompt = str(payload.get("prompt") or "").lower()
    await _maybe_refresh()
    return _route_detail(prompt)


@router.get("/health")
async def health():
    await _maybe_refresh()
    return {
        "status": "ok",
        "enabled": ENABLED,
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
