"""Tests for chat proxy model normalization."""
import json
import pytest
from unittest.mock import patch
from httpx import ASGITransport, AsyncClient, Response
from backend.main import app


@pytest.mark.asyncio
async def test_chat_proxy_strips_provider_prefix_from_model():
    captured = {}

    class FakeUpstreamClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, content, headers):
            captured["body"] = json.loads(content)
            return Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    with patch("backend.routes.chat.httpx.AsyncClient", FakeUpstreamClient):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/api/chat/completions", json={
                "model": "ubt26-llamacpp/qwen3.6-27b-q6",
                "messages": [{"role": "user", "content": "hi"}],
                "stream": False,
            })

    assert response.status_code == 200
    assert captured["body"]["model"] == "qwen3.6-27b-q6"
