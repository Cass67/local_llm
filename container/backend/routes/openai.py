"""Project-owned OpenAI-compatible endpoints."""

from fastapi import APIRouter, Request

from .. import active_runners
from ..clusters import list_desired
from .chat import proxy_chat_completions
from .models import output_limit

router = APIRouter(prefix="/v1", tags=["openai"])


def _context_window_for(family: str, profile: str | None = None) -> int | None:
    """Read context window from the profile this model actually runs under.

    The caller knows the live profile (the active/desired record names it); the
    accepted-model JSON only carries a pin that nothing updates on a profile
    switch, so trusting it reports a stale window. Fall back to that JSON only
    when the family has no profiles at all.
    """
    try:
        from .profiles import _load

        fam = _load().get("families", {}).get(family, {})
        profiles = fam.get("profiles", {})
        name = profile if profile in profiles else fam.get("default")
        ctx = profiles.get(name, {}).get("context")
        if ctx:
            return int(ctx)
    except Exception:  # nosec B110  # noqa: BLE001, S110
        pass
    try:
        from .models import _read_accepted_models

        for m in _read_accepted_models():
            if m.family == family or m.alias == family:
                return m.context
    except Exception:  # nosec B110  # noqa: BLE001, S110
        pass
    return None


# Effort levels advertised to harnesses. The Qwen3.6 template is binary, so the
# backend normalizes any level to enable_thinking=true (see routes/chat.py); the
# levels exist only so harnesses (Forge, opencode) expose a reasoning control.
_REASONING_OPTIONS = [{"type": "effort", "values": ["low", "medium", "high"]}]


def _vision_for(family: str, profile: str | None) -> bool:
    """True when the profile this model runs under loads an mmproj."""
    try:
        from .profiles import _load

        fam = _load().get("families", {}).get(family, {})
        profiles = fam.get("profiles", {})
        cfg = profiles.get(profile or fam.get("default")) or {}
        return bool(cfg.get("mmproj"))
    except Exception:  # nosec B110  # noqa: BLE001, S110
        return False


def _model_entry(ctx: int | None, vision: bool = False) -> dict:
    """Capability record in the models.dev/Forge map shape."""
    return {
        "reasoning": True,
        "temperature": True,
        "tool_call": True,
        "reasoning_options": _REASONING_OPTIONS,
        "limit": {"context": ctx or 0, "output": output_limit(ctx)},
        # Clients cannot infer this: llama-server never reports the projector,
        # so a vision model looks text-only and images get dropped client-side.
        "input": ["text", "image"] if vision else ["text"],
    }


@router.get("/models")
async def v1_models():
    """Router sentinel first, then running, then desired-but-idle.

    Emits both the standard OpenAI ``data`` list and a ``models`` map carrying
    reasoning capability. Forge parses ``models`` (and only there picks up
    ``reasoning_options`` -> the /effort control); plain OpenAI clients read
    ``data`` and ignore the extra key.
    """
    seen: set[str] = set()
    data: list[dict] = []
    models: dict[str, dict] = {}
    seen.add("router")
    # Filled from the models below, then spliced in at index 0 as the sentinel.
    # Forge (and any client that trusts the API) reads the router entry, not the
    # per-model ones, so leaving it at 0 made Forge fall back to its own default
    # and compact at ~32k against a 262144-token model.
    routed_ctx: list[int] = []
    routed_vision: list[bool] = []

    for source in (active_runners.list_active(), list_desired()):
        for entry in source:
            alias = str(entry.get("model") or "")
            family = str(entry.get("family") or alias)
            if not alias or alias in seen:
                continue
            seen.add(alias)
            ctx = _context_window_for(family, entry.get("profile"))
            vision = _vision_for(family, entry.get("profile"))
            rec: dict = {"id": alias, "object": "model", "owned_by": "local_llm"}
            if ctx:
                rec["context_window"] = ctx
            # Same budget as models[alias].limit.output, in the flat shape pi's
            # llama-cpp extension reads. Without it the client picks its own
            # default and truncates long replies.
            rec["max_tokens"] = output_limit(ctx)
            rec["input"] = ["text", "image"] if vision else ["text"]
            data.append(rec)
            models[alias] = _model_entry(ctx, vision)
            if ctx:
                routed_ctx.append(ctx)
            routed_vision.append(vision)

    # The router forwards to whichever model is live, so advertise the smallest
    # window it could land on -- overstating it makes a client overrun the ctx,
    # and vision only holds if every candidate has an mmproj.
    router_ctx = min(routed_ctx) if routed_ctx else None
    router_vision = bool(routed_vision) and all(routed_vision)
    router_rec: dict = {
        "id": "router",
        "object": "model",
        "owned_by": "local_llm",
        "max_tokens": output_limit(router_ctx),
    }
    if router_ctx:
        router_rec["context_window"] = router_ctx
    router_rec["input"] = ["text", "image"] if router_vision else ["text"]
    data.insert(0, router_rec)
    models = {"router": _model_entry(router_ctx, router_vision), **models}

    return {"object": "list", "data": data, "models": models}


@router.post("/chat/completions")
async def v1_chat_completions(request: Request):
    return await proxy_chat_completions(request)
