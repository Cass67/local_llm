"""Tests for chat proxy model normalization."""

import json
from unittest.mock import patch

import backend.routes.chat as chat_routes
import pytest
from backend.main import app
from httpx import ASGITransport, AsyncClient, Response


@pytest.mark.asyncio
async def test_chat_proxy_strips_provider_prefix_from_model(tmp_path, monkeypatch):
    import backend.config as cfg

    monkeypatch.setattr(cfg, "RUNNER_URL", "http://runner.test:18080/v1")
    monkeypatch.setattr(cfg, "RUNS_DIR", tmp_path)
    (tmp_path / "current-selection.json").write_text(json.dumps({"model": "qwen3.6-27b-q6"}))
    captured = {}

    class FakeUpstreamClient:
        def __init__(self, *args, **kwargs):
            assert args == ()
            # Incidental to this test: assert the proxy passes its own configured
            # timeout, not a literal, so tuning _PROXY_TIMEOUT does not break this.
            assert kwargs == {"timeout": chat_routes._PROXY_TIMEOUT}

        async def __aenter__(self):
            return self

        async def __aexit__(self, _exc_type, _exc, _tb):
            return None

        async def post(self, url, content, headers):
            assert url == "http://runner.test:18080/v1/chat/completions"
            assert headers == {"Content-Type": "application/json"}
            captured["body"] = json.loads(content)
            return Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    with patch("backend.routes.chat.httpx.AsyncClient", FakeUpstreamClient):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/chat/completions",
                json={
                    "model": "ubt26-llamacpp/qwen3.6-27b-q6",
                    "messages": [{"role": "user", "content": "hi"}],
                    "stream": False,
                },
            )

    assert response.status_code == 200
    assert captured["body"]["model"] == "qwen3.6-27b-q6"


@pytest.mark.asyncio
async def test_streaming_records_timings_from_the_final_chunk(tmp_path, monkeypatch):
    """Every real client streams, so a non-streaming-only recorder sees nothing."""
    import backend.config as cfg

    monkeypatch.setattr(cfg, "RUNNER_URL", "http://runner.test:18080/v1")
    monkeypatch.setattr(cfg, "RUNS_DIR", tmp_path)
    recorded = []
    monkeypatch.setattr(chat_routes, "append_chat_metric", recorded.append)

    chunks = [
        b'data: {"choices":[{"delta":{"content":"hi"}}]}\n\n',
        # llama-server attaches timings to the last chunk only
        b'data: {"choices":[{"delta":{}}],"timings":{"predicted_per_second":42.5,'
        b'"prompt_per_second":100.0,"draft_n":80,"draft_n_accepted":60}}\n\n',
        b"data: [DONE]\n\n",
    ]

    class FakeStream:
        status_code = 200

        async def aiter_raw(self):
            for chunk in chunks:
                yield chunk

    class FakeStreamContext:
        async def __aenter__(self):
            return FakeStream()

        async def __aexit__(self, *exc):
            return None

    class FakeUpstreamClient:
        def __init__(self, *args, **kwargs):
            pass

        def stream(self, *args, **kwargs):
            return FakeStreamContext()

        async def aclose(self):
            return None

    with patch("backend.routes.chat.httpx.AsyncClient", FakeUpstreamClient):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/chat/completions",
                json={
                    "model": "qwen3.6-27b-q6",
                    "messages": [{"role": "user", "content": "hi"}],
                    "stream": True,
                },
            )
            assert response.status_code == 200
            await response.aread()

    assert len(recorded) == 1
    assert recorded[0]["predicted_per_second"] == 42.5
    assert (recorded[0]["draft_n"], recorded[0]["draft_n_accepted"]) == (80, 60)
    assert json.loads((tmp_path / "latest-metrics.json").read_text())["draft_n"] == 80
