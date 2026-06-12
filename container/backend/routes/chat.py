"""Chat completion proxy to llama-server."""

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from ..config import LLAMA_SERVER_PORT

router = APIRouter(prefix="/api/chat", tags=["chat"])

LLAMA_SERVER_URL = f"http://127.0.0.1:{LLAMA_SERVER_PORT}/v1/chat/completions"


@router.post("/completions")
async def chat_completions(request: Request):
    """Proxy chat completion requests to llama-server."""
    body = await request.body()
    headers = {
        "Content-Type": request.headers.get("content-type", "application/json"),
    }

    async with httpx.AsyncClient(timeout=300.0) as client:
        upstream = await client.post(
            LLAMA_SERVER_URL,
            content=body,
            headers=headers,
        )

    if "text/event-stream" in upstream.headers.get("content-type", ""):
        return StreamingResponse(
            upstream.aiter_raw(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
            },
        )

    return StreamingResponse(
        upstream.aiter_raw(),
        status_code=upstream.status_code,
        media_type=upstream.headers.get("content-type", "application/json"),
    )
