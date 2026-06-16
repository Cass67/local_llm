"""Project-owned OpenAI-compatible endpoints."""

from fastapi import APIRouter, Request

from .. import active_runners
from .chat import proxy_chat_completions

router = APIRouter(prefix="/v1", tags=["openai"])


@router.get("/models")
async def v1_models():
    """List currently running models across all active clusters.

    Only models that are actually running are included here, since those are the
    only ones that can answer chat requests. The full accepted-model catalog is
    available via /api/models.
    """
    active = active_runners.list_active()
    # deduplicate by model alias in case of race (same model running twice)
    seen: set[str] = set()
    data = []
    for entry in active:
        alias = str(entry.get("model") or "")
        if alias and alias not in seen:
            seen.add(alias)
            data.append(
                {
                    "id": alias,
                    "object": "model",
                    "owned_by": "local_llm",
                    "backend": entry.get("backend"),
                    "cluster_id": entry.get("cluster_id"),
                }
            )
    return {"object": "list", "data": data}


@router.post("/chat/completions")
async def v1_chat_completions(request: Request):
    return await proxy_chat_completions(request)
