"""Power sampling and perf-per-watt."""

import time

import pytest
from backend import power
from backend.benchmark_store import BenchmarkStore


def test_tokens_per_watt():
    assert power.tokens_per_watt(40.0, 400.0) == 0.1
    assert power.tokens_per_watt(None, 400.0) is None
    assert power.tokens_per_watt(40.0, None) is None
    assert power.tokens_per_watt(40.0, 0) is None


def test_sampler_collects_and_averages(monkeypatch):
    readings = iter([100.0, 200.0, 300.0])
    monkeypatch.setattr(power, "read_psu_watts", lambda: next(readings, 300.0))
    monkeypatch.setattr(power, "read_gpu_watts", lambda: None)

    sampler = power.PowerSampler(interval_s=0.01)
    with sampler:
        time.sleep(0.08)
    result = sampler.result()
    assert result["psu_avg_w"] is not None
    assert result["psu_peak_w"] >= result["psu_avg_w"]
    assert result["gpu_avg_w"] is None
    assert result["samples"] > 0


def test_sampler_is_a_noop_without_sensors(monkeypatch):
    monkeypatch.setattr(power, "read_psu_watts", lambda: None)
    monkeypatch.setattr(power, "read_gpu_watts", lambda: None)
    sampler = power.PowerSampler(interval_s=0.01)
    with sampler:
        time.sleep(0.03)
    assert sampler.result() == {
        "psu_avg_w": None,
        "psu_peak_w": None,
        "gpu_avg_w": None,
        "gpu_peak_w": None,
        "samples": 0,
    }


def test_gpu_watts_sums_all_cards(monkeypatch):
    monkeypatch.setattr(
        power,
        "collect_amd_gpu_metrics",
        lambda: {"a": {"power_w": 120.0}, "b": {"power_w": 130.0}, "c": {"power_w": None}},
    )
    assert power.read_gpu_watts() == 250.0


def test_gpu_watts_none_when_unreadable(monkeypatch):
    monkeypatch.setattr(power, "collect_amd_gpu_metrics", lambda: {})
    assert power.read_gpu_watts() is None


# --- store schema ---


@pytest.fixture
def store(tmp_path):
    return BenchmarkStore(tmp_path / "b.sqlite3")


def test_power_columns_persist(store):
    run = store.create_run(
        endpoint_id=1,
        endpoint_name="Cluster: x",
        endpoint_base_url="http://127.0.0.1:3200/v1",
        model="m",
        prompt_text="p",
        response_text="r",
        output_chars=1,
        output_words=1,
        status="ok",
        throughput_tps=40.0,
        psu_avg_w=400.0,
        psu_peak_w=520.0,
        gpu_avg_w=330.0,
        tps_per_watt=0.1,
        profile="balanced",
    )
    assert run["tps_per_watt"] == 0.1
    assert run["psu_peak_w"] == 520.0
    assert run["profile"] == "balanced"


def test_runs_filter_by_profile(store):
    common = {
        "endpoint_id": 1,
        "endpoint_name": "e",
        "endpoint_base_url": "u",
        "model": "m",
        "prompt_text": "p",
        "response_text": "r",
        "output_chars": 1,
        "output_words": 1,
        "status": "ok",
    }
    store.create_run(profile="balanced", **common)
    store.create_run(profile="rccl", **common)
    result = store.list_runs({"profile": "rccl"})
    assert result["total"] == 1
    assert result["runs"][0]["profile"] == "rccl"


def test_migration_adds_columns_to_an_existing_db(tmp_path):
    path = tmp_path / "old.sqlite3"
    BenchmarkStore(path)  # create at current schema
    import sqlite3

    with sqlite3.connect(path) as conn:
        for column in ("psu_avg_w", "tps_per_watt", "profile"):
            conn.execute(f"alter table benchmark_runs drop column {column}")
    # Reopening must restore them rather than raise.
    reopened = BenchmarkStore(path)
    run = reopened.create_run(
        endpoint_id=1,
        endpoint_name="e",
        endpoint_base_url="u",
        model="m",
        prompt_text="p",
        response_text="r",
        output_chars=1,
        output_words=1,
        status="ok",
        tps_per_watt=0.2,
    )
    assert run["tps_per_watt"] == 0.2
