"""Chat completion proxy to project-owned runner."""

import json

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import Response, StreamingResponse
from .. import config
from . import switch as switch_routes

router = APIRouter(prefix="/api/chat", tags=["chat"])


def _normalize_model_name(body: bytes) -> bytes:
    """Strip provider prefix before forwarding to runner."""
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


def _is_stream_request(body: bytes) -> bool:
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return False
    return bool(payload.get("stream")) if isinstance(payload, dict) else False


def _request_model(body: bytes) -> str | None:
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return None
    model = payload.get("model") if isinstance(payload, dict) else None
    return model if isinstance(model, str) and model else None


def _current_model_id() -> str | None:
    path = config.RUNS_DIR / "current-selection.json"
    if not path.exists() or path.is_symlink():
        return None
    try:
        payload = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    model = payload.get("model") if isinstance(payload, dict) else None
    return model if isinstance(model, str) and model else None


def _ensure_requested_model(body: bytes) -> None:
    model = _request_model(body)
    if model and model != _current_model_id():
        switch_routes.switch_model_by_id(model)


def _record_metrics(body: bytes, response_body: bytes) -> None:
    try:
        request_payload = json.loads(body)
        response_payload = json.loads(response_body)
    except json.JSONDecodeError:
        return
    timings = response_payload.get("timings") if isinstance(response_payload, dict) else None
    if not isinstance(timings, dict):
        return
    model = request_payload.get("model") if isinstance(request_payload, dict) else None
    metrics = {
        "model": model,
        "predicted_per_second": timings.get("predicted_per_second"),
        "prompt_per_second": timings.get("prompt_per_second"),
        "draft_n": timings.get("draft_n"),
        "draft_n_accepted": timings.get("draft_n_accepted"),
    }
    config.RUNS_DIR.mkdir(parents=True, exist_ok=True)
    (config.RUNS_DIR / "latest-metrics.json").write_text(json.dumps(metrics, indent=2) + "\n")


async def proxy_chat_completions(request: Request):
    """Proxy chat completion requests to project-owned runner."""
    body = _normalize_model_name(await request.body())
    _ensure_requested_model(body)
    headers = {
        "Content-Type": request.headers.get("content-type", "application/json"),
    }

    if _is_stream_request(body):

        async def stream_runner():
            async with httpx.AsyncClient(timeout=300.0) as client:
                async with client.stream(
                    "POST",
                    f"{config.RUNNER_URL}/chat/completions",
                    content=body,
                    headers=headers,
                ) as upstream:
                    async for chunk in upstream.aiter_raw():
                        yield chunk

        return StreamingResponse(stream_runner(), media_type="text/event-stream")

    async with httpx.AsyncClient(timeout=300.0) as client:
        upstream = await client.post(
            f"{config.RUNNER_URL}/chat/completions",
            content=body,
            headers=headers,
        )

    content_type = upstream.headers.get("content-type", "application/json")
    _record_metrics(body, upstream.content)
    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        media_type=content_type,
    )


@router.post("/completions")
async def chat_completions(request: Request):
    return await proxy_chat_completions(request)
