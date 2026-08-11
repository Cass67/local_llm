"""Model router — picks model from keywords, forwards to backend."""

import json
import os
import re
import time
from pathlib import Path

import httpx
import router_anthropic
import router_responses
from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

# --- config ---

PORT = int(os.environ.get("ROUTER_PORT", "3200"))

_env_config = os.environ.get("ROUTER_CONFIG", "")
_STATE_CONFIG = (
    Path(_env_config)
    if _env_config
    else Path(os.environ.get("LOCAL_LLM_STATE_DIR", "/state")) / "router_rules.json"
)
_REPO_CONFIG = Path(__file__).parent.parent / "configs" / "router_rules.json"
_CONFIG_PATH = _STATE_CONFIG if _STATE_CONFIG.exists() else _REPO_CONFIG
_config_mtime: float = 0.0

# Runtime config — reloaded when the file changes
BACKEND_URL = "http://127.0.0.1:3100"

# No read timeout: long generations are bounded by the runner's own --timeout,
# not this proxy. connect/write stay bounded so a dead backend still fails fast.
_PROXY_TIMEOUT = httpx.Timeout(connect=10.0, read=None, write=30.0, pool=10.0)
DEFAULT_MODEL: str | None = None
DEFAULT_CLUSTER: str | None = None
HEALTH_INTERVAL: int = 10
RULES: list[dict] = []
ENABLED: bool = True
CLUSTER_REMAP: dict[str, str] = {}
# Send a request to an idle tier-eligible cluster instead of queueing it behind
# work on the primary. Off by default — it changes which GPU serves a prompt.
PREFER_IDLE: bool = False
# Log the decision the rules would make without acting on it, so rules can be
# tuned against real traffic before ENABLED is flipped on.
SHADOW: bool = False


def _reload_config() -> None:
    global \
        BACKEND_URL, \
        DEFAULT_MODEL, \
        DEFAULT_CLUSTER, \
        HEALTH_INTERVAL, \
        RULES, \
        ENABLED, \
        CLUSTER_REMAP, \
        PREFER_IDLE, \
        SHADOW, \
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
        DEFAULT_CLUSTER = cfg.get("default_cluster")
        HEALTH_INTERVAL = cfg.get("health_check_interval_s", 10)
        RULES = cfg.get("rules", [])
        ENABLED = cfg.get("enabled", True)
        PREFER_IDLE = bool(cfg.get("prefer_idle", False))
        SHADOW = bool(cfg.get("shadow", False))
        remap = cfg.get("cluster_remap", {})
        CLUSTER_REMAP = remap if isinstance(remap, dict) else {}
        _CONFIG_PATH = path
        _config_mtime = mtime
    except (OSError, json.JSONDecodeError):
        pass


_reload_config()

# "auto" (and empty) are sentinels meaning "let the router decide"
_ROUTE_SENTINELS = {"auto", "router", "local-auto", ""}

# --- health cache ---

_healthy_aliases: set[str] = set()
_cluster_to_model: dict[str, str] = {}  # cluster name → current model alias
_vision_aliases: set[str] = set()  # aliases whose *running* profile loaded an mmproj
_last_health_check: float = 0.0
# alias → requests this proxy currently has open against it. Exact and instant,
# unlike the fdinfo occupancy below, which is a 2s-sampled average.
_inflight: dict[str, int] = {}
# cluster name → GPU-equivalents busy, from the mgmt /api/gpu-status sampler
_cluster_occupancy: dict[str, float] = {}
# rolling record of routing decisions, newest last — read via /route/log
_decision_log: list[dict] = []
_DECISION_LOG_MAX = 200


def _log_decision(entry: dict) -> None:
    _decision_log.append({"ts": time.time(), **entry})
    if len(_decision_log) > _DECISION_LOG_MAX:
        del _decision_log[: len(_decision_log) - _DECISION_LOG_MAX]


def _acquire_inflight(alias: str):
    """Mark alias busy; returns the release callable.

    Streaming responses return as soon as headers arrive but keep generating for
    a long time afterwards, so the release has to travel with the generator
    rather than sit in a `with` block around the handler.
    """
    if not alias:
        return lambda: None
    _inflight[alias] = _inflight.get(alias, 0) + 1
    released = False

    def release() -> None:
        nonlocal released
        if released:
            return
        released = True
        remaining = _inflight.get(alias, 1) - 1
        if remaining > 0:
            _inflight[alias] = remaining
        else:
            _inflight.pop(alias, None)

    return release


def _busy_score(alias: str) -> float:
    """How loaded this alias is. In-flight requests dominate; occupancy breaks ties."""
    cluster = next((k for k, v in _cluster_to_model.items() if v == alias), None)
    occupancy = _cluster_occupancy.get(cluster, 0.0) if cluster else 0.0
    return _inflight.get(alias, 0) * 100.0 + occupancy


def _pick_least_busy(aliases: list[str]) -> str | None:
    """Least-loaded alias, preserving the caller's order as the tie-break."""
    healthy = [a for a in aliases if a in _healthy_aliases]
    if not healthy:
        return None
    return min(healthy, key=lambda a: (_busy_score(a), healthy.index(a)))


async def _refresh_health() -> None:
    global _healthy_aliases, _cluster_to_model, _vision_aliases, _last_health_check
    _reload_config()
    try:
        async with httpx.AsyncClient(timeout=5.0) as c:
            models_resp = await c.get(f"{BACKEND_URL}/v1/models")
            models_resp.raise_for_status()
            # "router" is this proxy's own alias — routing to it loops back here.
            _healthy_aliases = {
                m["id"] for m in models_resp.json().get("data", []) if m["id"] != "router"
            }

            profiles_resp = await c.get(f"{BACKEND_URL}/api/profiles")
            families = (
                profiles_resp.json().get("families", {}) if profiles_resp.status_code == 200 else {}
            )

            clusters_resp = await c.get(f"{BACKEND_URL}/api/clusters")
            if clusters_resp.status_code == 200:
                clusters = clusters_resp.json().get("clusters", [])
                old_map = _cluster_to_model.copy()
                active = [
                    c["active"]
                    for c in clusters
                    if c.get("active") and c["active"].get("running") and c["active"].get("model")
                ]
                _cluster_to_model = {
                    c["name"]: c["active"]["model"]
                    for c in clusters
                    if c.get("active") and c["active"].get("running") and c["active"].get("model")
                }
                # A model only sees images if the profile it was *launched with* set mmproj.
                _vision_aliases = {
                    a["model"]
                    for a in active
                    if families.get(a.get("family"), {})
                    .get("profiles", {})
                    .get(a.get("profile"), {})
                    .get("mmproj")
                }
                for name, model in sorted(_cluster_to_model.items()):
                    if old_map.get(name) != model:
                        print(f"router: active [{name}] {model}", flush=True)

            if PREFER_IDLE:
                await _refresh_occupancy(c)
    except Exception as exc:  # noqa: BLE001 — a probe failure must not stop routing
        print(f"router: health refresh failed: {exc}")
    _last_health_check = time.monotonic()


async def _refresh_occupancy(client: httpx.AsyncClient) -> None:
    """Per-cluster GPU-equivalents busy, from mgmt's fdinfo sampler."""
    global _cluster_occupancy
    try:
        resp = await client.get(f"{BACKEND_URL}/api/gpu-status")
        if resp.status_code != 200:
            return
        runners = resp.json().get("runners", [])
    except Exception:  # noqa: BLE001 — occupancy is an optimisation, never a hard dependency
        return
    _cluster_occupancy = {
        str(r.get("cluster_name")): float(r.get("aggregate_gpu_equiv") or 0.0)
        for r in runners
        if r.get("cluster_name")
    }


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
    """Configured default → default cluster's live model → any healthy model.

    The default_cluster hop matters: default_model names a specific alias, so it
    goes stale the moment that profile stops being the one loaded. Without it we
    fall to sorted-first, which is alphabetical, not "best" — that quietly parked
    every unmatched prompt on whichever cluster happened to sort first.
    """
    if DEFAULT_MODEL and DEFAULT_MODEL in _healthy_aliases:
        return DEFAULT_MODEL
    if DEFAULT_CLUSTER:
        alias = _cluster_to_model.get(_remap_cluster(DEFAULT_CLUSTER))
        if alias and alias in _healthy_aliases:
            return alias
    return next(iter(sorted(_healthy_aliases)), "")


def _is_healthy(alias: str) -> bool:
    return alias in _healthy_aliases


# --- routing ---


def _extract_user_messages(messages: list[dict]) -> list[str]:
    """Return all user message texts, most-recent first."""
    result = []
    for msg in reversed(messages):
        if msg.get("role") != "user":
            continue
        content = msg.get("content", "")
        if isinstance(content, str) and content.strip():
            result.append(content.strip().lower())
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text" and part["text"].strip():
                    result.append(part["text"].strip().lower())
                    break
    return result


_IMAGE_PART_TYPES = {"image_url", "image", "input_image"}


def _has_image(messages: list[dict]) -> bool:
    return any(
        isinstance(part, dict) and part.get("type") in _IMAGE_PART_TYPES
        for msg in messages
        for part in (msg.get("content") if isinstance(msg.get("content"), list) else [])
    )


def _keyword_in(keyword: str, prompt: str) -> bool:
    if not keyword.strip():
        return False
    if keyword[-1:].isalnum() and keyword[:1].isalnum():
        return re.search(rf"(?<![a-z0-9]){re.escape(keyword)}(?![a-z0-9])", prompt) is not None
    return keyword in prompt


# Structural signal detectors — operate on the raw (lowercased) prompt text.
# Each returns True/False. Keep them fast: no LLM, no network.
_SIGNAL_CHECKS: dict[str, "re.Pattern[str] | None"] = {}

_CODE_BLOCK_RE = re.compile(r"```|^\s{4}\S", re.MULTILINE)
# Mentioning a file, path, or identifier means the prompt is about a codebase,
# whatever verb it uses. Catches the long tail of phrasings no keyword list
# covers: "port this to go", "update the readme", "why is foo_bar returning 0".
_CODE_REF_RE = re.compile(
    r"`[^`]+`"
    r"|\b[\w-]+\.(?:py|ts|tsx|js|jsx|go|rs|rb|java|c|h|cpp|sh|json|ya?ml|toml|md|css|html|sql)\b"
    r"|(?:^|\s)[~.]?/[\w./-]+"
    r"|\b\w+_\w+\b"  # snake_case (prompts are lowercased, so camelCase is unreachable)
    r"|\b\w+\(\)"
)
_MATH_RE = re.compile(r"[∑∫∂∇∏√≈≠≤≥±×÷∈∉∩∪⊂⊃]|\$[^$]+\$|\\frac|\\sum|\\int")
_WORD_RE = re.compile(r"\S+")


def _eval_signal(signal: str, prompt: str) -> bool:
    match signal:
        case "has_code_block":
            return bool(_CODE_BLOCK_RE.search(prompt))
        case "has_code_ref":
            return bool(_CODE_REF_RE.search(prompt))
        case "has_math":
            return bool(_MATH_RE.search(prompt))
        case "long_prompt":
            return len(_WORD_RE.findall(prompt)) > 120
        case "short_prompt":
            return len(_WORD_RE.findall(prompt)) < 15
        case "is_question":
            stripped = prompt.strip()
            return stripped.endswith("?") and len(_WORD_RE.findall(stripped)) < 30
        case _:
            return False


def _match_signals(signals: list[str], prompt: str) -> str | None:
    """Return first signal that fires, or None."""
    return next((s for s in signals if _eval_signal(s, prompt)), None)


# Length/shape-only signals: they describe the *input* size, not the task, so a
# short prompt asking for a huge answer ("write a game") must never route on
# them. Kept as gates elsewhere but excluded from triggering a rule.
_WEAK_SIGNALS = {"short_prompt", "is_question"}


def _match_rule(prompt: str) -> tuple[int, dict] | None:
    """Return (rule index, routing result) for a prompt, or None if no rule matched.

    The index is the rule's position in the config, which is also its priority:
    hard-tier rules are listed first. Callers use it to pick the strongest match
    across a conversation.
    """
    for idx, rule in enumerate(RULES):
        keywords = rule.get("keywords", [])
        # Content-blind signals (length/shape only) must NOT trigger a rule on
        # their own — a bare "continue" or short edit would hijack the whole
        # turn to the "easy" cluster. Only keywords and content-based signals
        # (has_code_block, has_math) can trigger; weak signals are ignored.
        signals = [s for s in rule.get("signals", []) if s not in _WEAK_SIGNALS]
        matched_kw = next((kw for kw in keywords if _keyword_in(str(kw), prompt)), None)
        matched_sig = _match_signals(signals, prompt) if not matched_kw else None
        matched = matched_kw or (f"signal:{matched_sig}" if matched_sig else None)
        if not matched:
            continue
        raw_cluster = rule.get("cluster")
        remapped_cluster = _remap_cluster(raw_cluster) if raw_cluster else None
        chosen = _resolve_model(rule.get("model"), raw_cluster)

        if PREFER_IDLE and chosen and _busy_score(chosen) > 0:
            # Primary is mid-request. Every fallback on this rule is declared
            # tier-equivalent, so serving now on an idle one beats queueing.
            candidates = [chosen]
            for fb in rule.get("fallback", []):
                alias = _cluster_to_model.get(_remap_cluster(fb), fb)
                if alias not in candidates:
                    candidates.append(alias)
            idle = _pick_least_busy(candidates)
            if idle and idle != chosen:
                return idx, {
                    "model": idle,
                    "reason": "idle-fallback",
                    "rule": rule.get("name"),
                    "matched_keyword": matched,
                    "cluster": raw_cluster,
                    "remapped_cluster": remapped_cluster,
                    "busy_primary": chosen,
                    "busy_score": _busy_score(chosen),
                }

        if chosen:
            return idx, {
                "model": chosen,
                "reason": "rule",
                "rule": rule.get("name"),
                "matched_keyword": matched,
                "cluster": raw_cluster,
                "remapped_cluster": remapped_cluster,
            }
        for fb in rule.get("fallback", []):
            fb_cluster = _remap_cluster(fb)
            fb_alias = _cluster_to_model.get(fb_cluster, fb)
            if fb_alias in _healthy_aliases:
                return idx, {
                    "model": fb_alias,
                    "reason": "fallback",
                    "rule": rule.get("name"),
                    "matched_keyword": matched,
                    "cluster": raw_cluster,
                    "remapped_cluster": remapped_cluster,
                    "fallback": fb,
                    "remapped_fallback": fb_cluster,
                }
        # Primary + fallbacks all down. Falling through to a later rule silently
        # demotes the prompt to an easier tier, so say so.
        print(
            f"router: rule {rule.get('name')!r} matched {matched!r} but cluster "
            f"{remapped_cluster!r} is not running — falling through",
            flush=True,
        )
    return None


def _route_detail(messages: list[dict]) -> dict:
    """Route on the strongest match anywhere in the conversation.

    Rules are ordered hard-tier first, so the lowest matching index is the most
    demanding intent the session has expressed — and difficulty only ratchets up.
    This replaces anchoring on the *first* classifiable message, which pinned the
    tier symmetrically: one incidental "look that up on the internet" turn sent
    every later coding turn to the easy cluster for the rest of the session.
    Short follow-ups ("continue", "now add tests") still inherit the hard tier,
    which is what anchoring was for. Stateless — resent history is the state.
    """
    # Images are a hard constraint, not a preference: a text-only runner silently
    # drops the image parts and answers about nothing. Override any keyword rule.
    if _has_image(messages):
        vision = sorted(_vision_aliases & _healthy_aliases)
        if vision:
            return {"model": vision[0], "reason": "vision"}
        print("router: image in request but no vision-capable model running", flush=True)

    best: tuple[int, dict] | None = None
    for prompt in _extract_user_messages(messages):
        match = _match_rule(prompt)
        if match is not None and (best is None or match[0] < best[0]):
            best = match
    if best is not None:
        return best[1]
    return {"model": _default_model(), "reason": "default"}


def _route(messages: list[dict]) -> str:
    return str(_route_detail(messages).get("model") or "")


# --- proxy ---


def _is_stream(payload: dict) -> bool:
    return bool(payload.get("stream"))


async def _proxy_stream(payload: dict, request: Request, release=None) -> Response:
    release = release or (lambda: None)
    client = httpx.AsyncClient(timeout=_PROXY_TIMEOUT)
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
        release()
        return JSONResponse({"detail": "backend unavailable"}, status_code=503)

    if upstream.status_code != 200:
        body_bytes = await upstream.aread()
        await stream_ctx.__aexit__(None, None, None)
        await client.aclose()
        release()
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
            release()

    return StreamingResponse(stream_upstream(), media_type="text/event-stream")


async def _proxy_translated_stream(payload: dict, translator, release=None) -> Response:
    """Stream chat completions upstream, re-emitting each chunk in another dialect."""
    release = release or (lambda: None)
    # Both dialects report token usage in their terminal event; llama.cpp only
    # sends it on a streamed response when asked.
    payload["stream_options"] = {"include_usage": True}
    client = httpx.AsyncClient(timeout=_PROXY_TIMEOUT)
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
        release()
        return JSONResponse({"detail": "backend unavailable"}, status_code=503)

    if upstream.status_code != 200:
        body_bytes = await upstream.aread()
        await stream_ctx.__aexit__(None, None, None)
        await client.aclose()
        release()
        return JSONResponse(
            {"detail": body_bytes.decode("utf-8", errors="replace")},
            status_code=upstream.status_code,
        )

    async def translate():
        try:
            yield translator.start()
            async for line in upstream.aiter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if not data or data == "[DONE]":
                    continue
                try:
                    yield translator.chunk(json.loads(data))
                except json.JSONDecodeError:
                    continue
            yield translator.stop()
        finally:
            await stream_ctx.__aexit__(None, None, None)
            await client.aclose()
            release()

    return StreamingResponse(translate(), media_type="text/event-stream")


async def _post_chat(payload: dict) -> tuple[dict | None, Response | None]:
    """Non-streaming chat completions call. Returns (completion, error_response)."""
    try:
        async with httpx.AsyncClient(timeout=_PROXY_TIMEOUT) as client:
            upstream = await client.post(
                f"{BACKEND_URL}/v1/chat/completions",
                content=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
    except httpx.HTTPError:
        return None, JSONResponse({"detail": "backend unavailable"}, status_code=503)
    if upstream.status_code != 200:
        return None, Response(
            content=upstream.content,
            status_code=upstream.status_code,
            media_type=upstream.headers.get("content-type", "application/json"),
        )
    try:
        return upstream.json(), None
    except json.JSONDecodeError:
        return None, JSONResponse({"detail": "invalid backend response"}, status_code=502)


async def _pick_model(requested: str, messages: list[dict], api: str) -> str | None:
    """Route unless the caller named a model that is actually loaded.

    Claude Code and Codex send their own hardcoded model names (claude-*, gpt-*),
    so a name we do not serve means "route this", not "404".
    """
    await _maybe_refresh()
    if requested and requested in _healthy_aliases:
        chosen = requested
    elif ENABLED:
        chosen = _route(messages)
    else:
        chosen = _default_model()
    if not chosen:
        return None
    last_prompt = (_extract_user_messages(messages) or [""])[0]
    cluster = next((k for k, v in _cluster_to_model.items() if v == chosen), "?")
    print(f"router: [{cluster}] {chosen} ({api}) ← {last_prompt[:80]!r}", flush=True)
    return chosen


async def _proxy_nonstream(payload: dict) -> Response:
    async with httpx.AsyncClient(timeout=_PROXY_TIMEOUT) as client:
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
    except Exception as exc:  # noqa: BLE001 — surface upstream failures as 502
        return JSONResponse({"detail": str(exc)}, status_code=502)


@router.post("/v1/chat/completions")
async def v1_chat_completions(request: Request):
    body = await request.body()
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return JSONResponse({"detail": "invalid JSON"}, status_code=400)

    model_val = payload.get("model") or ""
    explicit_model = bool(model_val) and model_val not in _ROUTE_SENTINELS

    await _maybe_refresh()
    messages = payload.get("messages", [])
    last_prompt = (_extract_user_messages(messages) or [""])[0]
    if ENABLED and not explicit_model:
        detail = _route_detail(messages)
        chosen = str(detail.get("model") or "")
        if not chosen:
            return JSONResponse({"detail": "no healthy model available"}, status_code=503)
        payload["model"] = chosen
        cluster = next((k for k, v in _cluster_to_model.items() if v == chosen), "?")
        print(f"router: [{cluster}] {chosen} ← {last_prompt[:80]!r}", flush=True)
        _log_decision({"prompt": last_prompt[:200], "dispatched": chosen, **detail})
    else:
        model = payload.get("model", "")
        cluster = next((k for k, v in _cluster_to_model.items() if v == model), "client-specified")
        print(f"router: [{cluster}] {model} ← {last_prompt[:80]!r}", flush=True)
        if SHADOW:
            # Score the rules against real traffic without acting on them.
            shadow = _route_detail(messages)
            _log_decision(
                {
                    "prompt": last_prompt[:200],
                    "dispatched": model,
                    "shadow": True,
                    "would_route_to": shadow.get("model"),
                    "would_differ": shadow.get("model") != model,
                    **{k: v for k, v in shadow.items() if k != "model"},
                }
            )
            if shadow.get("model") != model:
                print(
                    f"router: [shadow] would have routed to {shadow.get('model')} "
                    f"({shadow.get('reason')}: {shadow.get('rule')})",
                    flush=True,
                )

    release = _acquire_inflight(str(payload.get("model") or ""))
    try:
        if _is_stream(payload):
            return await _proxy_stream(payload, request, release)
        response = await _proxy_nonstream(payload)
    except BaseException:
        release()
        raise
    else:
        release()
        return response


@router.post("/v1/messages")
async def v1_messages(request: Request):
    """Anthropic Messages API — Claude Code."""
    try:
        payload = json.loads(await request.body())
    except json.JSONDecodeError:
        return JSONResponse(router_anthropic.error("invalid JSON"), status_code=400)

    chat = router_anthropic.to_chat(payload)
    chosen = await _pick_model(payload.get("model") or "", chat["messages"], "anthropic")
    if not chosen:
        return JSONResponse(
            router_anthropic.error("no healthy model available", "overloaded_error"),
            status_code=503,
        )
    chat["model"] = chosen

    release = _acquire_inflight(chosen)
    if payload.get("stream"):
        return await _proxy_translated_stream(
            chat, router_anthropic.AnthropicStream(chosen), release
        )

    chat.pop("stream", None)
    try:
        completion, err = await _post_chat(chat)
    finally:
        release()
    if err is not None:
        return err
    return JSONResponse(router_anthropic.from_chat(completion, chosen))


@router.post("/v1/messages/count_tokens")
async def v1_count_tokens(request: Request):
    try:
        payload = json.loads(await request.body())
    except json.JSONDecodeError:
        return JSONResponse(router_anthropic.error("invalid JSON"), status_code=400)
    return JSONResponse(router_anthropic.count_tokens(payload))


@router.post("/v1/responses")
async def v1_responses(request: Request):
    """OpenAI Responses API — Codex CLI."""
    try:
        payload = json.loads(await request.body())
    except json.JSONDecodeError:
        return JSONResponse(router_responses.error("invalid JSON"), status_code=400)

    chat = router_responses.to_chat(payload)
    chosen = await _pick_model(payload.get("model") or "", chat["messages"], "responses")
    if not chosen:
        return JSONResponse(
            router_responses.error("no healthy model available", "server_error"), status_code=503
        )
    chat["model"] = chosen

    release = _acquire_inflight(chosen)
    if payload.get("stream"):
        return await _proxy_translated_stream(
            chat, router_responses.ResponsesStream(chosen), release
        )

    chat.pop("stream", None)
    try:
        completion, err = await _post_chat(chat)
    finally:
        release()
    if err is not None:
        return err
    return JSONResponse(router_responses.from_chat(completion, chosen))


@router.post("/route/preview")
async def route_preview(request: Request):
    body = await request.body()
    try:
        payload = json.loads(body) if body else {}
    except json.JSONDecodeError:
        payload = {}
    # Accept either a messages array or a legacy plain-text prompt string
    messages = payload.get("messages") or [
        {"role": "user", "content": str(payload.get("prompt") or "")}
    ]
    await _maybe_refresh()
    return _route_detail(messages)


@router.get("/route/log")
async def route_log(limit: int = 50, differing_only: bool = False):
    """Recent routing decisions. In shadow mode this is the rule-tuning feedback loop."""
    entries = _decision_log
    if differing_only:
        entries = [e for e in entries if e.get("would_differ")]
    recent = entries[-max(1, min(limit, _DECISION_LOG_MAX)) :]
    shadowed = [e for e in _decision_log if e.get("shadow")]
    return {
        "entries": list(reversed(recent)),
        "total": len(_decision_log),
        "shadow": SHADOW,
        "shadow_would_differ": sum(1 for e in shadowed if e.get("would_differ")),
        "shadow_total": len(shadowed),
    }


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
        "prefer_idle": PREFER_IDLE,
        "shadow": SHADOW,
        "inflight": dict(_inflight),
        "occupancy": _cluster_occupancy,
    }


app.include_router(router)

if __name__ == "__main__":
    import asyncio

    import uvicorn

    asyncio.run(_refresh_health())
    uvicorn.run(app, host="0.0.0.0", port=PORT)  # noqa: S104 # nosec B104
