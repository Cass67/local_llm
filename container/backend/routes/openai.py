"""Project-owned OpenAI-compatible endpoints."""

import json

from fastapi import APIRouter, Request

from .. import config
from .chat import proxy_chat_completions
from .models import _read_accepted_models

router = APIRouter(prefix="/v1", tags=["openai"])


@router.get("/models")
async def v1_models():
    """List accepted models without querying an external runtime router."""
    selected = None
    selection_path = config.RUNS_DIR / "current-selection.json"
    if selection_path.exists() and not selection_path.is_symlink():
        try:
            selection = json.loads(selection_path.read_text())
            selected = selection.get("model") if isinstance(selection, dict) else None
        except (OSError, json.JSONDecodeError):
            selected = None

    models = _read_accepted_models()
    if selected:
        models.sort(key=lambda model: 0 if model.alias == selected else 1)

    return {
        "object": "list",
        "data": [
            {
                "id": model.alias,
                "object": "model",
                "owned_by": "local_llm",
                "context": model.context,
                "backend": model.backend,
                "reasoning": model.reasoning,
            }
            for model in models
        ],
    }


@router.post("/chat/completions")
async def v1_chat_completions(request: Request):
    return await proxy_chat_completions(request)
