"""Tests for local_llm OpenAI chat proxy and metrics capture."""

import json
from unittest.mock import patch

import httpx
import pytest
from httpx import ASGITransport, AsyncClient, Response


def _make_fake_client(captured=None, response_json=None):
    resp = response_json or {"choices": [{"message": {"content": "ok"}}]}

    class FakeUpstreamClient:
        def __init__(self, *_, **__):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, _exc_type, _exc, _tb):
            return None

        async def post(self, url, content, **_kwargs):
            if captured is not None:
                captured["url"] = url
                captured["body"] = json.loads(content)
            return Response(200, json=resp)

    return FakeUpstreamClient


@pytest.mark.asyncio
async def test_v1_chat_completions_proxies_to_active_cluster(tmp_path, monkeypatch):
    import backend.config as cfg

    monkeypatch.setattr(cfg, "RUNNER_URL", "http://fallback.test:8080/v1")
    monkeypatch.setattr(cfg, "RUNS_DIR", tmp_path)
    captured = {}

    active = [{"cluster_id": "c1", "model": "qwopus", "port": 9001}]

    monkeypatch.setattr(
        "backend.routes.chat.httpx.AsyncClient",
        _make_fake_client(
            captured,
            {
                "choices": [{"message": {"content": "ok"}}],
                "timings": {
                    "predicted_per_second": 42.5,
                    "prompt_per_second": 123.0,
                    "draft_n": 3,
                    "draft_n_accepted": 2,
                },
            },
        ),
    )

    from backend.main import app

    with patch("backend.routes.chat.active_runners.list_active", return_value=active):
        with patch(
            "backend.routes.chat.active_runners.runner_url_for_model",
            return_value="http://127.0.0.1:9001/v1",
        ):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post(
                    "/v1/chat/completions",
                    json={"model": "local/qwopus", "messages": [{"role": "user", "content": "hi"}]},
                )

    assert response.status_code == 200
    assert captured["url"] == "http://127.0.0.1:9001/v1/chat/completions"
    assert captured["body"]["model"] == "qwopus"


@pytest.mark.asyncio
async def test_v1_chat_no_auto_switch_returns_first_active_fallback(tmp_path, monkeypatch):
    """Chat does NOT auto-switch models. Unknown model falls back to first active cluster."""
    import backend.config as cfg

    monkeypatch.setattr(cfg, "RUNNER_URL", "http://fallback.test:8080/v1")
    monkeypatch.setattr(cfg, "RUNS_DIR", tmp_path)
    captured = {}

    active = [{"cluster_id": "c1", "model": "gemma", "port": 9001}]

    monkeypatch.setattr("backend.routes.chat.httpx.AsyncClient", _make_fake_client(captured))

    from backend.main import app

    with patch("backend.routes.chat.active_runners.list_active", return_value=active):
        with patch("backend.routes.chat.active_runners.runner_url_for_model", return_value=None):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post(
                    "/v1/chat/completions",
                    json={
                        "model": "unknown-model",
                        "messages": [{"role": "user", "content": "hi"}],
                    },
                )

    assert response.status_code == 200
    # Routes to the first active cluster's port, not the fallback RUNNER_URL
    assert "9001" in captured["url"]


@pytest.mark.asyncio
async def test_v1_chat_injects_thinking_off_when_client_omits_setting(tmp_path, monkeypatch):
    import backend.config as cfg

    monkeypatch.setattr(cfg, "RUNNER_URL", "http://runner.test:8080/v1")
    monkeypatch.setattr(cfg, "RUNS_DIR", tmp_path)
    captured = {}

    monkeypatch.setattr("backend.routes.chat.httpx.AsyncClient", _make_fake_client(captured))

    from backend.main import app

    with patch("backend.routes.chat.active_runners.runner_url_for_model", return_value=None):
        with patch("backend.routes.chat.active_runners.list_active", return_value=[]):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post(
                    "/v1/chat/completions",
                    json={"model": "qwen", "messages": [{"role": "user", "content": "hi"}]},
                )

    assert response.status_code == 200
    # Thinking is ON by default; no override injected when client omits the setting
    assert "chat_template_kwargs" not in captured["body"]


@pytest.mark.asyncio
async def test_v1_chat_stream_returns_503_when_runner_is_down(tmp_path, monkeypatch):
    import backend.config as cfg

    monkeypatch.setattr(cfg, "RUNS_DIR", tmp_path)
    monkeypatch.setattr(cfg, "RUNNER_URL", "http://runner.test:8080/v1")

    class FailingStreamContext:
        async def __aenter__(self):
            raise httpx.ConnectError("All connection attempts failed")

        async def __aexit__(self, _exc_type, _exc, _tb):
            return None

    class FakeUpstreamClient:
        def __init__(self, *_, **__):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, _exc_type, _exc, _tb):
            return None

        async def aclose(self):
            return None

        def stream(self, _method, _url, **_kwargs):
            return FailingStreamContext()

    monkeypatch.setattr("backend.routes.chat.httpx.AsyncClient", FakeUpstreamClient)

    from backend.main import app

    with patch("backend.routes.chat.active_runners.runner_url_for_model", return_value=None):
        with patch("backend.routes.chat.active_runners.list_active", return_value=[]):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post(
                    "/v1/chat/completions",
                    json={
                        "model": "qwen",
                        "messages": [{"role": "user", "content": "hi"}],
                        "stream": True,
                    },
                )

    assert response.status_code == 503
    assert response.json()["detail"] == "runner unavailable"
