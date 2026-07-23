"""Project-owned OpenAI-compatible endpoints."""

from fastapi import APIRouter, Request

from .. import active_runners
from ..clusters import list_desired
from .chat import proxy_chat_completions

router = APIRouter(prefix="/v1", tags=["openai"])


def _context_window_for(family: str) -> int | None:
    """Read context window from the model's active profile."""
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


def _model_entry(ctx: int | None) -> dict:
    """Capability record in the models.dev/Forge map shape."""
    return {
        "reasoning": True,
        "temperature": True,
        "tool_call": True,
        "reasoning_options": _REASONING_OPTIONS,
        "limit": {"context": ctx or 0, "output": 0},
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
    data = [{"id": "router", "object": "model", "owned_by": "local_llm"}]
    models: dict[str, dict] = {"router": _model_entry(None)}
    seen.add("router")

    for source in (active_runners.list_active(), list_desired()):
        for entry in source:
            alias = str(entry.get("model") or "")
            family = str(entry.get("family") or alias)
            if not alias or alias in seen:
                continue
            seen.add(alias)
            ctx = _context_window_for(family)
            rec: dict = {"id": alias, "object": "model", "owned_by": "local_llm"}
            if ctx:
                rec["context_window"] = ctx
            data.append(rec)
            models[alias] = _model_entry(ctx)

    return {"object": "list", "data": data, "models": models}


@router.post("/chat/completions")
async def v1_chat_completions(request: Request):
    return await proxy_chat_completions(request)
