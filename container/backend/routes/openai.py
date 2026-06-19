"""Project-owned OpenAI-compatible endpoints."""

from fastapi import APIRouter, Request

from .. import active_runners
from ..clusters import list_desired
from .chat import proxy_chat_completions

router = APIRouter(prefix="/v1", tags=["openai"])


@router.get("/models")
async def v1_models():
    """Router sentinel first, then running, then desired-but-idle."""
    seen: set[str] = set()
    data = [{"id": "router", "object": "model", "owned_by": "local_llm"}]
    seen.add("router")

    for entry in active_runners.list_active():
        alias = str(entry.get("model") or "")
        if alias and alias not in seen:
            seen.add(alias)
            data.append({"id": alias, "object": "model", "owned_by": "local_llm"})

    for entry in list_desired():
        alias = str(entry.get("model") or "")
        if alias and alias not in seen:
            seen.add(alias)
            data.append({"id": alias, "object": "model", "owned_by": "local_llm"})

    return {"object": "list", "data": data}


@router.post("/chat/completions")
async def v1_chat_completions(request: Request):
    return await proxy_chat_completions(request)
