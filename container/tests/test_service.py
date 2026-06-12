"""Tests for runtime service detection."""

import json


def test_detect_running_model_prefers_runner_state_over_stale_selection(tmp_path, monkeypatch):
    import backend.config as cfg
    from backend.service import detect_running_model

    monkeypatch.setattr(cfg, "RUNS_DIR", tmp_path)
    (tmp_path / "current-selection.json").write_text(json.dumps({"model": "qwen3.6-27b-q5km"}))
    (tmp_path / "current-runner.json").write_text(
        json.dumps({"model": "gemma-4-12b", "container": {"name": "local-llm-runner"}})
    )

    status = detect_running_model()

    assert status == {"status": "active", "family": "gemma-4-12b", "ctx": None}
