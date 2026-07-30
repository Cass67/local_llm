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
