"""Chat completion proxy to project-owned runner."""

import json
import time

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from .. import active_runners, config, tracing
from .stats import append_chat_metric

router = APIRouter(prefix="/api/chat", tags=["chat"])


def _prepare_runner_payload(body: bytes) -> bytes:
    """Normalize model names and default OpenWebUI-style requests to visible answers."""
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return body
    if not isinstance(payload, dict):
        return body

    changed = False
    model = payload.get("model")
    if isinstance(model, str) and "/" in model:
        payload["model"] = model.rsplit("/", 1)[1]
        changed = True

    template_kwargs = payload.get("chat_template_kwargs")
    if config.DISABLE_THINKING_BY_DEFAULT:
        if not isinstance(template_kwargs, dict):
            template_kwargs = {}
            payload["chat_template_kwargs"] = template_kwargs
            changed = True
        if "enable_thinking" not in template_kwargs:
            template_kwargs["enable_thinking"] = False
            changed = True

    return json.dumps(payload).encode("utf-8") if changed else body


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


def _resolve_runner_url(body: bytes) -> str:
    """Return the runner URL for the model requested in the body.

    Looks up whichever active cluster is running that model. Falls back to the
    global RUNNER_URL for single-cluster backward compatibility (when only one
    cluster is active and no specific model is requested).
    """
    model = _request_model(body)
    if model:
        url = active_runners.runner_url_for_model(model)
        if url:
            return url
    # Backward-compat: use the first active cluster's port, or global default
    active = active_runners.list_active()
    if active:
        port = active[0].get("port")
        if isinstance(port, int):
            return f"http://127.0.0.1:{port}/v1"
    return config.RUNNER_URL


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
        "ts": time.time(),
    }
    config.RUNS_DIR.mkdir(parents=True, exist_ok=True)
    (config.RUNS_DIR / "latest-metrics.json").write_text(json.dumps(metrics, indent=2) + "\n")
    append_chat_metric(metrics)


async def proxy_chat_completions(request: Request):
    """Proxy chat completion requests to the appropriate cluster runner."""
    body = _prepare_runner_payload(await request.body())
    runner_url = _resolve_runner_url(body)

    model = _request_model(body)
    for entry in active_runners.list_active():
        if entry.get("model") == model or entry.get("family") == model or model is None:
            if cluster_id := entry.get("cluster_id"):
                active_runners.touch(str(cluster_id))
            break
    headers = {
        "Content-Type": request.headers.get("content-type", "application/json"),
    }

    if _is_stream_request(body):
        generation = tracing.open_generation(body, stream=True)
        req_start = time.perf_counter()

        client = httpx.AsyncClient(timeout=300.0)
        stream_context = client.stream(
            "POST",
            f"{runner_url}/chat/completions",
            content=body,
            headers=headers,
        )
        try:
            upstream = await stream_context.__aenter__()
        except httpx.HTTPError:
            await client.aclose()
            tracing.close_generation(generation, "", error="runner unavailable")
            return JSONResponse({"detail": "runner unavailable"}, status_code=503)

        if upstream.status_code != 200:
            body_bytes = await upstream.aread()
            await stream_context.__aexit__(None, None, None)
            await client.aclose()
            try:
                detail = json.loads(body_bytes).get(
                    "error", body_bytes.decode("utf-8", errors="replace")
                )
            except (json.JSONDecodeError, AttributeError):
                detail = body_bytes.decode("utf-8", errors="replace")
            tracing.close_generation(generation, "", error=f"HTTP {upstream.status_code}: {detail}")
            return JSONResponse({"detail": detail}, status_code=upstream.status_code)

        async def stream_runner():
            first_token = True
            ttft_ms: float | None = None
            parts: list[str] = []
            prompt_tokens: int | None = None
            completion_tokens: int | None = None

            try:
                async for raw in upstream.aiter_raw():
                    if first_token and raw.strip():
                        ttft_ms = (time.perf_counter() - req_start) * 1000
                        first_token = False
                    for line in raw.decode("utf-8", errors="ignore").splitlines():
                        if not line.startswith("data: ") or line == "data: [DONE]":
                            continue
                        try:
                            data = json.loads(line[6:])
                            delta = (data.get("choices") or [{}])[0].get("delta", {})
                            if delta.get("content"):
                                parts.append(delta["content"])
                            usage = data.get("usage")
                            if isinstance(usage, dict):
                                prompt_tokens = usage.get("prompt_tokens")
                                completion_tokens = usage.get("completion_tokens")
                        except (json.JSONDecodeError, IndexError, KeyError):
                            pass
                    yield raw
            finally:
                tracing.close_generation(
                    generation,
                    "".join(parts),
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    ttft_ms=ttft_ms,
                    duration_ms=(time.perf_counter() - req_start) * 1000,
                )
                await stream_context.__aexit__(None, None, None)
                await client.aclose()

        return StreamingResponse(stream_runner(), media_type="text/event-stream")

    generation = tracing.open_generation(body, stream=False)
    req_start = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=300.0) as client:
            upstream = await client.post(
                f"{runner_url}/chat/completions",
                content=body,
                headers=headers,
            )
    except Exception as exc:
        tracing.close_generation(generation, "", error=str(exc))
        raise

    duration_ms = (time.perf_counter() - req_start) * 1000
    content_type = upstream.headers.get("content-type", "application/json")
    _record_metrics(body, upstream.content)

    if upstream.status_code == 200:
        try:
            resp = json.loads(upstream.content)
            choices = resp.get("choices") or []
            resp_text = (choices[0].get("message") or {}).get("content", "") if choices else ""
            usage = resp.get("usage") or {}
            timings = resp.get("timings") or {}
            tracing.close_generation(
                generation,
                resp_text,
                prompt_tokens=usage.get("prompt_tokens"),
                completion_tokens=usage.get("completion_tokens"),
                duration_ms=duration_ms,
                predicted_per_second=timings.get("predicted_per_second"),
            )
        except (json.JSONDecodeError, IndexError):
            tracing.close_generation(generation, "", duration_ms=duration_ms)
    else:
        tracing.close_generation(
            generation, "", error=f"HTTP {upstream.status_code}", duration_ms=duration_ms
        )

    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        media_type=content_type,
    )


@router.post("/completions")
async def chat_completions(request: Request):
    return await proxy_chat_completions(request)
