"""Chat completion proxy to llama-swap."""
import json

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import Response, StreamingResponse
from ..config import LLAMA_SERVER_PORT

router = APIRouter(prefix="/api/chat", tags=["chat"])

LLAMA_SERVER_URL = f"http://127.0.0.1:{LLAMA_SERVER_PORT}/v1/chat/completions"


def _normalize_model_name(body: bytes) -> bytes:
    """Strip provider prefix before forwarding to llama-swap."""
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return body
    if isinstance(payload, dict) and isinstance(payload.get("model"), str):
        model = payload["model"]
        if "/" in model:
            payload["model"] = model.rsplit("/", 1)[1]
        return json.dumps(payload).encode("utf-8")
    return body


@router.post("/completions")
async def chat_completions(request: Request):
    """Proxy chat completion requests to llama-swap."""
    body = _normalize_model_name(await request.body())
    headers = {
        "Content-Type": request.headers.get("content-type", "application/json"),
    }

    async with httpx.AsyncClient(timeout=300.0) as client:
        upstream = await client.post(
            LLAMA_SERVER_URL,
            content=body,
            headers=headers,
        )

    content_type = upstream.headers.get("content-type", "application/json")
    if "text/event-stream" not in content_type:
        return Response(
            content=upstream.content,
            status_code=upstream.status_code,
            media_type=content_type,
        )

    return StreamingResponse(
        upstream.aiter_raw(),
        status_code=upstream.status_code,
        media_type=content_type,
    )
