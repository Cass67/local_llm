"""Pi models.json compatible endpoint."""

from fastapi import APIRouter, Request

from .models import _read_accepted_models

router = APIRouter(prefix="/api/pi", tags=["pi"])


@router.get("/models")
async def pi_models_json(request: Request):
    base_url = str(request.url.replace(path="/v1", query=""))
    models = _read_accepted_models()

    provider_models = []
    for model in models:
        context = model.context or 131072
        provider_models.append(
            {
                "id": model.alias,
                "name": model.model_name,
                "context": context,
                "contextWindow": context,
                "maxTokens": min(context // 2, 49152),
                "reasoning": model.reasoning,
                "backend": model.backend,
            }
        )

    return {
        "providers": {
            "ubt26-llamacpp": {
                "baseUrl": base_url,
                "api": "openai-completions",
                "apiKey": "",
                "compat": {
                    "supportsDeveloperRole": False,
                    "supportsReasoningEffort": False,
                },
                "models": provider_models,
            },
        },
    }
