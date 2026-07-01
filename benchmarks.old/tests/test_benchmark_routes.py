from importlib import import_module
from pathlib import Path

import httpx
from backend import config
from backend.main import app
from fastapi.testclient import TestClient

benchmark = import_module("backend.routes.benchmark")


def test_endpoint_prompt_and_summary_api(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(config, "RUNS_DIR", tmp_path)
    benchmark._store.cache_clear()
    client = TestClient(app)

    endpoint = client.post(
        "/api/local-llm/benchmark/endpoints",
        json={"name": "local", "base_url": "http://localhost:8080/v1", "api_key": "secret"},
    )
    assert endpoint.status_code == 200
    assert endpoint.json()["api_key_set"] is True
    assert "secret" not in endpoint.text

    prompt = client.post(
        "/api/local-llm/benchmark/prompts",
        json={"name": "Short", "text": "Say hi"},
    )
    assert prompt.status_code == 200
    assert client.get("/api/local-llm/benchmark/summary").json()["total_runs"] == 0


def test_models_and_run_api(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(config, "RUNS_DIR", tmp_path)
    benchmark._store.cache_clear()
    client = TestClient(app)
    endpoint = client.post(
        "/api/local-llm/benchmark/endpoints",
        json={"name": "swap", "base_url": "http://server/v1"},
    ).json()

    class FakeResponse:
        def __init__(self, payload, elapsed=0.1):
            self._payload = payload
            self.elapsed = elapsed

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    async def fake_get(self, _url, **_kwargs):
        return FakeResponse({"data": [{"id": "model-a"}]})

    async def fake_post(self, _url, **_kwargs):
        return FakeResponse(
            {
                "choices": [{"message": {"content": "hello world"}}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
            },
            elapsed=0.2,
        )

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    models = client.post(
        "/api/local-llm/benchmark/models",
        json={"endpoint_id": endpoint["id"]},
    )
    assert models.status_code == 200
    assert models.json()["models"] == ["model-a"]

    run = client.post(
        "/api/local-llm/benchmark/runs",
        json={"endpoint_id": endpoint["id"], "model": "model-a", "prompt_text": "Say hi"},
    )
    assert run.status_code == 200
    payload = run.json()
    assert payload["status"] == "ok"
    assert payload["response_text"] == "hello world"
    assert payload["completion_tokens"] == 2
    assert client.get("/api/local-llm/benchmark/runs?model=model-a").json()["total"] == 1
