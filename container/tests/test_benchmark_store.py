from importlib import import_module
from pathlib import Path

BenchmarkStore = import_module("backend.benchmark_store").BenchmarkStore


def test_endpoint_prompt_and_run_persist(tmp_path: Path):
    store = BenchmarkStore(tmp_path / "benchmarks.sqlite3")
    endpoint = store.create_endpoint(
        name="ubt26 swap",
        base_url="http://ubt26:8080/v1",
        api_key="secret-value",
    )
    prompt = store.create_prompt(
        name="Tiny coding",
        text="Write a Python hello world.",
    )

    run = store.create_run(
        endpoint_id=endpoint["id"],
        endpoint_name=endpoint["name"],
        endpoint_base_url=endpoint["base_url"],
        model="test-model",
        prompt_id=prompt["id"],
        prompt_name=prompt["name"],
        prompt_text=prompt["text"],
        response_text="print('hello')",
        latency_ms=123.4,
        duration_ms=456.7,
        output_chars=14,
        output_words=1,
        prompt_tokens=5,
        completion_tokens=7,
        total_tokens=12,
        throughput_tps=15.3,
        throughput_cps=30.6,
        status="ok",
        error=None,
    )

    assert endpoint["api_key_set"] is True
    assert "secret-value" not in str(store.list_endpoints())
    assert store.list_prompts()[0]["name"] == "Tiny coding"
    assert store.list_runs({})["runs"][0]["id"] == run["id"]
    assert store.summary()["total_runs"] == 1
    assert store.summary()["best_throughput_tps"] == 15.3


def test_run_filters(tmp_path: Path):
    store = BenchmarkStore(tmp_path / "benchmarks.sqlite3")
    endpoint = store.create_endpoint("local", "http://localhost:8080/v1", None)
    prompt = store.create_prompt("Short", "Say hi")
    store.create_run(
        endpoint_id=endpoint["id"],
        endpoint_name="local",
        endpoint_base_url=endpoint["base_url"],
        model="model-a",
        prompt_id=prompt["id"],
        prompt_name="Short",
        prompt_text="Say hi",
        response_text="hi",
        latency_ms=10,
        duration_ms=20,
        output_chars=2,
        output_words=1,
        prompt_tokens=None,
        completion_tokens=None,
        total_tokens=None,
        throughput_tps=None,
        throughput_cps=100,
        status="ok",
        error=None,
    )

    assert store.list_runs({"model": "model-a"})["total"] == 1
    assert store.list_runs({"model": "missing"})["total"] == 0
