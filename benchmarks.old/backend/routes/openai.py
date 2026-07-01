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


@router.get("/models")
async def v1_models():
    """Router sentinel first, then running, then desired-but-idle."""
    seen: set[str] = set()
    data = [{"id": "router", "object": "model", "owned_by": "local_llm"}]
    seen.add("router")

    for entry in active_runners.list_active():
        alias = str(entry.get("model") or "")
        family = str(entry.get("family") or alias)
        if alias and alias not in seen:
            seen.add(alias)
            rec: dict = {"id": alias, "object": "model", "owned_by": "local_llm"}
            ctx = _context_window_for(family)
            if ctx:
                rec["context_window"] = ctx
            data.append(rec)

    for entry in list_desired():
        alias = str(entry.get("model") or "")
        family = str(entry.get("family") or alias)
        if alias and alias not in seen:
            seen.add(alias)
            rec = {"id": alias, "object": "model", "owned_by": "local_llm"}
            ctx = _context_window_for(family)
            if ctx:
                rec["context_window"] = ctx
            data.append(rec)

    return {"object": "list", "data": data}


@router.post("/chat/completions")
async def v1_chat_completions(request: Request):
    return await proxy_chat_completions(request)
