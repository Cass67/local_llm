"""Tests for local_llm OpenAI chat proxy and metrics capture."""

import json

import httpx
from httpx import ASGITransport, AsyncClient, Response
import pytest
from unittest.mock import patch


@pytest.mark.asyncio
async def test_v1_chat_completions_proxies_to_runner_and_records_metrics(tmp_path, monkeypatch):
    import backend.config as cfg

    monkeypatch.setattr(cfg, "RUNNER_URL", "http://runner.test:8080/v1")
    monkeypatch.setattr(cfg, "RUNS_DIR", tmp_path)
    (tmp_path / "current-selection.json").write_text(json.dumps({"model": "qwopus"}))
    captured = {}

    class FakeUpstreamClient:
        def __init__(self, *args, **kwargs):
            assert args == ()
            assert kwargs == {"timeout": 300.0}

        async def __aenter__(self):
            return self

        async def __aexit__(self, _exc_type, _exc, _tb):
            return None

        async def post(self, url, content, headers):
            assert headers["Content-Type"] == "application/json"
            captured["url"] = url
            captured["body"] = json.loads(content)
            return Response(
                200,
                json={
                    "choices": [{"message": {"content": "ok"}}],
                    "timings": {
                        "predicted_per_second": 42.5,
                        "prompt_per_second": 123.0,
                        "draft_n": 3,
                        "draft_n_accepted": 2,
                    },
                },
            )

    monkeypatch.setattr("backend.routes.chat.httpx.AsyncClient", FakeUpstreamClient)
    from backend.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/v1/chat/completions",
            json={"model": "local/qwopus", "messages": [{"role": "user", "content": "hi"}]},
        )

    assert response.status_code == 200
    assert captured["url"] == "http://runner.test:8080/v1/chat/completions"
    assert captured["body"]["model"] == "qwopus"
    metrics = json.loads((tmp_path / "latest-metrics.json").read_text())
    assert metrics["model"] == "qwopus"
    assert metrics["predicted_per_second"] == 42.5
    assert metrics["prompt_per_second"] == 123.0
    assert metrics["draft_n"] == 3
    assert metrics["draft_n_accepted"] == 2


@pytest.mark.asyncio
async def test_v1_chat_switches_runner_when_requested_model_differs(tmp_path, monkeypatch):
    import backend.config as cfg

    accepted = tmp_path / "accepted"
    accepted.mkdir(parents=True)
    (accepted / "qwen.json").write_text(
        json.dumps(
            {
                "family": "qwen",
                "alias": "qwen",
                "model_name": "qwen",
                "profile": "reliable",
                "backend": "vulkan",
                "reasoning": False,
                "model_path": "/models/qwen.gguf",
                "config": {},
            }
        )
    )
    (tmp_path / "current-selection.json").write_text(json.dumps({"model": "gemma"}))
    monkeypatch.setattr(cfg, "RUNS_DIR", tmp_path)
    monkeypatch.setattr(cfg, "ACCEPTED_DIR", accepted)
    monkeypatch.setattr(cfg, "RUNNER_URL", "http://runner.test:8080/v1")

    class FakeUpstreamClient:
        def __init__(self, *_, **__):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, _exc_type, _exc, _tb):
            return None

        async def post(self, url, content, headers):
            assert headers["Content-Type"] == "application/json"
            return Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    monkeypatch.setattr("backend.routes.chat.httpx.AsyncClient", FakeUpstreamClient)
    with patch("backend.routes.switch.switch_model_by_id", return_value=None) as switch:
        from backend.main import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/v1/chat/completions",
                json={"model": "qwen", "messages": [{"role": "user", "content": "hi"}]},
            )

    assert response.status_code == 200
    switch.assert_called_once_with("qwen")


@pytest.mark.asyncio
async def test_v1_chat_stream_returns_503_when_runner_is_down(tmp_path, monkeypatch):
    import backend.config as cfg

    monkeypatch.setattr(cfg, "RUNS_DIR", tmp_path)
    (tmp_path / "current-selection.json").write_text(json.dumps({"model": "qwen"}))
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

        def stream(self, _method, _url, content, headers):
            assert json.loads(content)["model"] == "qwen"
            assert headers["Content-Type"] == "application/json"
            return FailingStreamContext()

    monkeypatch.setattr("backend.routes.chat.httpx.AsyncClient", FakeUpstreamClient)
    from backend.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/v1/chat/completions",
            json={"model": "qwen", "messages": [{"role": "user", "content": "hi"}], "stream": True},
        )

    assert response.status_code == 503
    assert response.json()["detail"] == "runner unavailable"


@pytest.mark.asyncio
async def test_v1_chat_stream_preserves_finish_reason(tmp_path, monkeypatch):
    import backend.config as cfg

    monkeypatch.setattr(cfg, "RUNS_DIR", tmp_path)
    (tmp_path / "current-selection.json").write_text(json.dumps({"model": "qwen"}))
    monkeypatch.setattr(cfg, "RUNNER_URL", "http://runner.test:8080/v1")

    class FakeStreamResponse:
        headers = {"content-type": "text/event-stream"}
        status_code = 200

        async def aiter_raw(self):
            yield b'data: {"choices":[{"finish_reason":null,"delta":{"content":"ok"}}]}\n\n'
            yield b'data: {"choices":[{"finish_reason":"stop","delta":{}}]}\n\n'
            yield b"data: [DONE]\n\n"

    class FakeStreamContext:
        async def __aenter__(self):
            return FakeStreamResponse()

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

        def stream(self, method, url, content, headers):
            assert method == "POST"
            assert url == "http://runner.test:8080/v1/chat/completions"
            assert headers["Content-Type"] == "application/json"
            return FakeStreamContext()

    monkeypatch.setattr("backend.routes.chat.httpx.AsyncClient", FakeUpstreamClient)
    from backend.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        async with client.stream(
            "POST",
            "/v1/chat/completions",
            json={"model": "qwen", "messages": [{"role": "user", "content": "hi"}], "stream": True},
        ) as response:
            body = b"".join([chunk async for chunk in response.aiter_raw()]).decode()

    assert response.status_code == 200
    assert 'finish_reason":"stop"' in body
    assert "[DONE]" in body
