"""Tests for current model endpoint."""
import json
import pytest
from unittest.mock import patch
from httpx import ASGITransport, AsyncClient


@pytest.fixture
def temp_state(tmp_path, monkeypatch):
    accepted = tmp_path / "accepted"
    launchers = tmp_path / "launchers"
    accepted.mkdir(parents=True)
    launchers.mkdir(parents=True)

    model_data = {
        "family": "qwen",
        "alias": "qwen3.6-27b-q6",
        "model_name": "Qwen3.6 27B",
        "profile": "reliable",
        "backend": "rocm",
        "launcher_file": str(launchers / "start-qwen.sh"),
        "remote_start": "./start-qwen.sh",
    }
    (accepted / "qwen.json").write_text(json.dumps(model_data, indent=2))
    (launchers / "start-qwen.sh").write_text("#!/usr/bin/env bash\necho ok\n")
    (launchers / "start-qwen.sh").chmod(0o755)

    # Write current-model.env
    (tmp_path / "current-model.env").write_text(
        "REMOTE_SCRIPT=./start-qwen.sh\nREMOTE_PROFILE=reliable\n"
    )

    import backend.config as cfg

    monkeypatch.setattr(cfg, "RUNS_DIR", tmp_path)
    monkeypatch.setattr(cfg, "ACCEPTED_DIR", accepted)
    monkeypatch.setattr(cfg, "LAUNCHERS_DIR", launchers)
    monkeypatch.setattr(cfg, "LLAMA_CPP_DIR", tmp_path)
    return tmp_path


@pytest.mark.asyncio
async def test_current_model_returns_running_model(temp_state):
    from backend.main import app

    with patch(
        "backend.routes.switch.get_llama_server_status", return_value="active"
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/models/current")

    assert response.status_code == 200
    data = response.json()
    assert data["family"] == "qwen"
    assert data["profile"] == "reliable"
    assert data["running"] is True
    assert "llama_server" in data
    assert data["llama_server"]["status"] == "active"


@pytest.mark.asyncio
async def test_current_model_when_no_env_file(tmp_path, monkeypatch):
    accepted = tmp_path / "accepted"
    launchers = tmp_path / "launchers"
    accepted.mkdir(parents=True)
    launchers.mkdir(parents=True)

    import backend.config as cfg

    monkeypatch.setattr(cfg, "RUNS_DIR", tmp_path)
    monkeypatch.setattr(cfg, "ACCEPTED_DIR", accepted)
    monkeypatch.setattr(cfg, "LAUNCHERS_DIR", launchers)
    monkeypatch.setattr(cfg, "LLAMA_CPP_DIR", tmp_path)

    from backend.main import app

    with patch(
        "backend.routes.switch.get_llama_server_status", return_value="inactive"
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/models/current")

    assert response.status_code == 200
    data = response.json()
    assert data["running"] is False
    assert data["family"] == "unknown"
