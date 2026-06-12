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


def test_run_install_downloads_and_registers_llama_swap_model(tmp_path, monkeypatch):
    import backend.config as cfg
    from backend import cli

    models = tmp_path / "models"
    accepted = tmp_path / "accepted"
    models.mkdir()
    accepted.mkdir()
    swap_config = tmp_path / "config.yaml"
    swap_config.write_text(
        "models:\n\n"
        '  "existing":\n'
        '    name: "Existing"\n\n'
        "routing:\n"
        "  router:\n"
        "    use: group\n"
        "    settings:\n"
        "      groups:\n"
        '        "dual-gpu":\n'
        "          swap: true\n"
        "          exclusive: true\n"
        "          members:\n"
        "            - gemma-4-31b\n"
    )
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
    monkeypatch.setattr(cfg, "LLAMA_SWAP_CONFIG", swap_config)

    with patch("backend.cli._restart_llama_swap") as restart:
        result = cli.run_install(
            "Jackrong/Qwopus3.6-27B-v2-MTP-GGUF",
            "Qwopus3.6-27B-v2-MTP-Q5_K_M.gguf",
            "reliable",
        )

    assert result["status"] == "installed"
    assert result["family"] == "qwopus3.6-27b-v2-mtp-q5km"
    config_text = swap_config.read_text()
    assert '"qwopus3.6-27b-v2-mtp-q5km"' in config_text
    assert "--split-mode layer" in config_text
    assert "--reasoning off" in config_text
    assert "            - qwopus3.6-27b-v2-mtp-q5km\n" in config_text
    metadata = json.loads((accepted / "qwopus3.6-27b-v2-mtp-q5km.json").read_text())
    assert metadata["repo"] == "Jackrong/Qwopus3.6-27B-v2-MTP-GGUF"
    restart.assert_called_once_with()
