"""Langfuse request tracing (SDK v2) — disabled gracefully if env vars are absent."""

from __future__ import annotations

import json
import os
from typing import Any

ENABLED = bool(os.environ.get("LANGFUSE_PUBLIC_KEY") and os.environ.get("LANGFUSE_SECRET_KEY"))

_client: Any = None


def _get_client() -> Any:
    global _client
    if not ENABLED:
        return None
    if _client is None:
        try:
            from langfuse import Langfuse  # noqa: PLC0415

            _client = Langfuse(
                public_key=os.environ["LANGFUSE_PUBLIC_KEY"],
                secret_key=os.environ["LANGFUSE_SECRET_KEY"],
                # Langfuse is served under /traces (NEXT_PUBLIC_BASE_PATH), so its
                # ingestion API lives at /traces/api/public/ingestion. The SDK appends
                # /api/public/ingestion to this host, so the base path must be included
                # or every POST 404s and traces are silently dropped.
                host=os.environ.get("LANGFUSE_HOST", "http://localhost:3004/traces"),
            )
        except Exception:  # noqa: BLE001 — tracing must never break client init
            return None
    return _client


def _parse_body(body: bytes) -> tuple[list[Any], str | None]:
    try:
        payload = json.loads(body)
        if not isinstance(payload, dict):
            return [], None
        return payload.get("messages", []), payload.get("model")
    except json.JSONDecodeError:
        return [], None


def open_generation(body: bytes, *, stream: bool) -> Any:
    """Open a Langfuse trace+generation. Returns a generation handle or None."""
    client = _get_client()
    if client is None:
        return None
    try:
        messages, model = _parse_body(body)
        trace = client.trace(
            name="chat-completion",
            input=messages,
            metadata={"model": model, "stream": stream},
        )
        return trace.generation(
            name="llama-cpp",
            model=model or "unknown",
            input=messages,
        )
    except Exception:  # noqa: BLE001 — tracing must never break a request
        return None


def close_generation(
    generation: Any,
    output: str,
    *,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    duration_ms: float | None = None,
    ttft_ms: float | None = None,
    predicted_per_second: float | None = None,
    error: str | None = None,
) -> None:
    if generation is None:
        return
    try:
        meta: dict[str, Any] = {}
        if ttft_ms is not None:
            meta["ttft_ms"] = round(ttft_ms, 1)
        if duration_ms is not None:
            meta["duration_ms"] = round(duration_ms, 1)
        if predicted_per_second is not None:
            meta["predicted_per_second"] = round(predicted_per_second, 2)

        usage: dict[str, int] = {}
        if prompt_tokens is not None:
            usage["input"] = prompt_tokens
        if completion_tokens is not None:
            usage["output"] = completion_tokens

        generation.end(
            output=output,
            level="ERROR" if error else "DEFAULT",
            status_message=error,
            usage=usage or None,
            metadata=meta or None,
        )
    except Exception:  # noqa: BLE001, S110  # nosec B110  (tracing must never break a request)
        pass
