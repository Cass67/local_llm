"""Chat completion proxy to project-owned runner."""

import asyncio
import json
import time

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import Response, StreamingResponse

from .. import active_runners, config, tracing
from .stats import append_chat_metric

router = APIRouter(prefix="/api/chat", tags=["chat"])

# No read timeout: long generations are bounded by the runner's own --timeout,
# not the proxy. connect/write stay bounded so a dead runner still fails fast.
_PROXY_TIMEOUT = httpx.Timeout(connect=10.0, read=None, write=30.0, pool=10.0)

# Strings that mean "no thinking". Any other effort level maps to thinking-on,
# since the Qwen3.6 template is binary (graded budgets are ignored by the runner).
_THINKING_OFF = {"none", "off", "false", "disabled", "no"}


def _as_thinking_bool(v: object) -> bool | None:
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.strip().lower() not in _THINKING_OFF
    return None


def _resolve_thinking(payload: dict) -> bool | None:
    """Reduce whatever thinking signal a client sent (any harness format) to on/off.

    Returns None when the request carries no thinking signal at all, so the caller
    can fall back to the server default.
    """
    tk = payload.get("chat_template_kwargs")
    if isinstance(tk, dict) and "enable_thinking" in tk:
        return _as_thinking_bool(tk["enable_thinking"])
    if "enable_thinking" in payload:
        return _as_thinking_bool(payload["enable_thinking"])
    if "reasoning_effort" in payload:
        return _as_thinking_bool(payload["reasoning_effort"])
    reasoning = payload.get("reasoning")  # openrouter/together: {effort|enabled}
    if isinstance(reasoning, dict):
        if "enabled" in reasoning:
            return _as_thinking_bool(reasoning["enabled"])
        if "effort" in reasoning:
            return _as_thinking_bool(reasoning["effort"])
    elif isinstance(reasoning, (bool, str)):
        return _as_thinking_bool(reasoning)
    thinking = payload.get("thinking")  # deepseek: {type: enabled|disabled}
    if isinstance(thinking, dict):
        if "type" in thinking:
            return thinking["type"] != "disabled"
        if "enabled" in thinking:
            return _as_thinking_bool(thinking["enabled"])
    elif isinstance(thinking, bool):
        return thinking
    return None


def _prepare_runner_payload(body: bytes) -> bytes:
    """Normalize model names and translate any harness's thinking control to the
    runner's chat_template_kwargs.enable_thinking (the model is binary on/off)."""
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

    want = _resolve_thinking(payload)
    if want is None and config.DISABLE_THINKING_BY_DEFAULT:
        want = False
    if want is not None:
        template_kwargs = payload.get("chat_template_kwargs")
        if not isinstance(template_kwargs, dict):
            template_kwargs = {}
            payload["chat_template_kwargs"] = template_kwargs
        if template_kwargs.get("enable_thinking") != want:
            template_kwargs["enable_thinking"] = want
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

    model = _request_model(body)

    # Detect whether we need to reload before serving
    reload_cluster = None
    if model and not active_runners.runner_url_for_model(model):
        from ..clusters import list_clusters, read_desired

        for cluster in list_clusters():
            desired = read_desired(cluster.id)
            if desired and desired.get("model") == model:
                reload_cluster = cluster
                break

    if not reload_cluster:
        for entry in active_runners.list_active():
            if entry.get("model") == model or entry.get("family") == model or model is None:
                if cluster_id := entry.get("cluster_id"):
                    active_runners.touch(str(cluster_id))
                break

    headers = {"Content-Type": request.headers.get("content-type", "application/json")}

    if _is_stream_request(body):
        generation = tracing.open_generation(body, stream=True)
        req_start = time.perf_counter()

        async def stream_runner():
            # Notify the client and reload if the cluster was idle-unloaded
            if reload_cluster:
                # role delta first, then content — matches OpenAI streaming format
                role_chunk = json.dumps(
                    {
                        "id": "chatcmpl-loading",
                        "object": "chat.completion.chunk",
                        "model": model or "router",
                        "choices": [
                            {"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}
                        ],
                    }
                )
                yield f"data: {role_chunk}\n\n".encode()
                notice = json.dumps(
                    {
                        "id": "chatcmpl-loading",
                        "object": "chat.completion.chunk",
                        "model": model or "router",
                        "choices": [
                            {
                                "index": 0,
                                "delta": {"content": "⏳ *Loading model, please wait...*\n\n"},
                                "finish_reason": None,
                            }
                        ],
                    }
                )
                yield f"data: {notice}\n\n".encode()

                from .clusters import _resolve_accepted

                # Run load in background; send keep-alives every 10s so the connection stays open
                load_task = asyncio.create_task(
                    asyncio.to_thread(
                        active_runners.ensure_running, reload_cluster, _resolve_accepted
                    )
                )
                while not load_task.done():
                    try:
                        await asyncio.wait_for(asyncio.shield(load_task), timeout=10.0)
                    except TimeoutError:
                        yield b": keep-alive\n\n"
                await load_task  # propagate any exception

                for entry in active_runners.list_active():
                    if entry.get("model") == model or entry.get("family") == model:
                        if cluster_id := entry.get("cluster_id"):
                            active_runners.touch(str(cluster_id))
                        break

            runner_url = _resolve_runner_url(body)
            first_token = True
            ttft_ms: float | None = None
            parts: list[str] = []
            prompt_tokens: int | None = None
            completion_tokens: int | None = None

            client = httpx.AsyncClient(timeout=_PROXY_TIMEOUT)
            stream_context = client.stream(
                "POST", f"{runner_url}/chat/completions", content=body, headers=headers
            )
            try:
                upstream = await stream_context.__aenter__()
            except httpx.HTTPError:
                await client.aclose()
                tracing.close_generation(generation, "", error="runner unavailable")
                return

            if upstream.status_code != 200:
                await upstream.aread()
                await stream_context.__aexit__(None, None, None)
                await client.aclose()
                tracing.close_generation(generation, "", error=f"HTTP {upstream.status_code}")
                return

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

    if reload_cluster:
        from .clusters import _resolve_accepted

        await asyncio.to_thread(active_runners.ensure_running, reload_cluster, _resolve_accepted)
        for entry in active_runners.list_active():
            if entry.get("model") == model or entry.get("family") == model:
                if cluster_id := entry.get("cluster_id"):
                    active_runners.touch(str(cluster_id))
                break

    runner_url = _resolve_runner_url(body)
    generation = tracing.open_generation(body, stream=False)
    req_start = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=_PROXY_TIMEOUT) as client:
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
