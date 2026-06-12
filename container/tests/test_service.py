"""Tests for runtime service detection."""

import json
from io import BytesIO
from unittest.mock import patch
import urllib.request


def test_detect_running_model_prefers_actual_running_over_stale_selection(tmp_path, monkeypatch):
    import backend.config as cfg
    from backend.service import detect_running_model

    monkeypatch.setattr(cfg, "RUNS_DIR", tmp_path)
    monkeypatch.setattr(cfg, "LLAMA_SWAP_URL", "http://llama-swap")
    (tmp_path / "current-selection.json").write_text(json.dumps({"model": "qwen3.6-27b-q5km"}))

    class Response(BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, _exc_type, _exc, _tb):
            return None

    payload = json.dumps({"running": [{"model": "gemma-4-12b", "state": "ready"}]})
    with patch.object(urllib.request, "urlopen", return_value=Response(payload.encode())):
        status = detect_running_model()

    assert status == {"status": "active", "family": "gemma-4-12b", "ctx": None}
