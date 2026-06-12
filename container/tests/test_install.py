"""Tests for install endpoint."""

import json
import sys
import types
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from backend.main import app


@pytest.mark.asyncio
async def test_install_model_success():
    with patch(
        "backend.routes.search.cli.run_install",
        return_value={"status": "installed", "family": "qwen-test", "alias": "qwen-test-q6"},
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/search/install",
                json={
                    "repo": "TheBloke/qwen-Q6_K-GGUF",
                    "file": "qwen.Q6_K.gguf",
                    "profile": "balanced",
                },
            )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "installed"


@pytest.mark.asyncio
async def test_install_model_failure():
    with patch(
        "backend.routes.search.cli.run_install",
        return_value={"status": "error", "detail": "download failed: disk full"},
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/search/install",
                json={
                    "repo": "TheBloke/qwen-Q6_K-GGUF",
                    "file": "qwen.Q6_K.gguf",
                    "profile": "balanced",
                },
            )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "error"
    assert "disk full" in data["detail"]


def test_run_install_error_includes_phase_context_and_logs(tmp_path, monkeypatch):
    import backend.config as cfg
    from backend import cli

    models = tmp_path / "models"
    accepted = tmp_path / "accepted"
    models.mkdir()
    accepted.mkdir()

    def fake_hf_hub_download(repo_id, filename, cache_dir):
        assert repo_id == "Jackrong/Qwopus3.6-27B-Coder-MTP-GGUF"
        assert filename == "Qwopus3.6-27B-Coder-MTP-Q5_K_M.gguf"
        assert cache_dir == models
        raise RuntimeError("HTTP 502 Bad Gateway")

    fake_hf = types.ModuleType("huggingface_hub")
    setattr(fake_hf, "hf_hub_download", fake_hf_hub_download)
    monkeypatch.setitem(sys.modules, "huggingface_hub", fake_hf)
    monkeypatch.setattr(cfg, "MODELS_CACHE_DIR", models)
    monkeypatch.setattr(cfg, "ACCEPTED_DIR", accepted)

    result = cli.run_install(
        "Jackrong/Qwopus3.6-27B-Coder-MTP-GGUF",
        "Qwopus3.6-27B-Coder-MTP-Q5_K_M.gguf",
        "balanced",
    )

    assert result == {
        "status": "error",
        "phase": "download",
        "repo": "Jackrong/Qwopus3.6-27B-Coder-MTP-GGUF",
        "file": "Qwopus3.6-27B-Coder-MTP-Q5_K_M.gguf",
        "profile": "balanced",
        "detail": "download failed for Jackrong/Qwopus3.6-27B-Coder-MTP-GGUF / Qwopus3.6-27B-Coder-MTP-Q5_K_M.gguf: HTTP 502 Bad Gateway",
        "logs": [
            "install balanced: Jackrong/Qwopus3.6-27B-Coder-MTP-GGUF / Qwopus3.6-27B-Coder-MTP-Q5_K_M.gguf",
            "download failed: HTTP 502 Bad Gateway",
        ],
    }
    assert not any(accepted.iterdir())


def test_run_install_downloads_and_writes_project_metadata(tmp_path, monkeypatch):
    import backend.config as cfg
    from backend import cli

    models = tmp_path / "models"
    accepted = tmp_path / "accepted"
    models.mkdir()
    accepted.mkdir()
    downloaded = models / "models--Jackrong--Qwopus" / "snapshots" / "abc" / "Qwopus.Q5_K_M.gguf"
    downloaded.parent.mkdir(parents=True)
    downloaded.write_text("fake")

    def fake_hf_hub_download(repo_id, filename, cache_dir):
        assert repo_id == "Jackrong/Qwopus3.6-27B-v2-MTP-GGUF"
        assert filename == "Qwopus3.6-27B-v2-MTP-Q5_K_M.gguf"
        assert cache_dir == models
        return str(downloaded)

    fake_hf = types.ModuleType("huggingface_hub")
    setattr(fake_hf, "hf_hub_download", fake_hf_hub_download)
    monkeypatch.setitem(sys.modules, "huggingface_hub", fake_hf)
    monkeypatch.setattr(cfg, "MODELS_CACHE_DIR", models)
    monkeypatch.setattr(cfg, "ACCEPTED_DIR", accepted)

    result = cli.run_install(
        "Jackrong/Qwopus3.6-27B-v2-MTP-GGUF",
        "Qwopus3.6-27B-v2-MTP-Q5_K_M.gguf",
        "reliable",
    )

    assert result["status"] == "installed"
    assert result["family"] == "qwopus3.6-27b-v2-mtp-q5km"
    metadata = json.loads((accepted / "qwopus3.6-27b-v2-mtp-q5km.json").read_text())
    assert metadata["repo"] == "Jackrong/Qwopus3.6-27B-v2-MTP-GGUF"
    assert metadata["model_path"] == str(downloaded)
    assert metadata["config"]["split_mode"] == "layer"
    assert metadata["config"]["tensor_split"] == "1,1"
