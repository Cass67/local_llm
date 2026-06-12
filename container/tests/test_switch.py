"""Tests for switch endpoint."""

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
        "model_name": "Qwen3.6 27B Heretic Q6_K",
        "profile": "reliable",
        "context": 131072,
        "backend": "rocm",
        "launcher_file": str(launchers / "start-qwen.sh"),
        "remote_start": "./start-qwen.sh",
        "reasoning": False,
    }
    (accepted / "qwen.json").write_text(json.dumps(model_data, indent=2))
    (launchers / "start-qwen.sh").write_text("#!/usr/bin/env bash\necho ok\n")
    (launchers / "start-qwen.sh").chmod(0o755)

    import backend.config as cfg

    monkeypatch.setattr(cfg, "RUNS_DIR", tmp_path)
    monkeypatch.setattr(cfg, "ACCEPTED_DIR", accepted)
    monkeypatch.setattr(cfg, "LAUNCHERS_DIR", launchers)
    monkeypatch.setattr(cfg, "LLAMA_CPP_DIR", tmp_path)
    return tmp_path


@pytest.mark.asyncio
async def test_switch_model_restarts_service(temp_state):
    from backend.main import app

    with patch("backend.routes.switch.restart_llama_server") as mock_restart:
        mock_restart.return_value = True

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/models/switch",
                json={
                    "family": "qwen",
                    "profile": "reliable",
                },
            )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "switched"
    assert data["family"] == "qwen"
    assert data["profile"] == "reliable"

    env_file = temp_state / "current-model.env"
    assert env_file.exists()
    content = env_file.read_text()
    assert "REMOTE_SCRIPT=./start-qwen.sh" in content
    assert "REMOTE_PROFILE=reliable" in content


@pytest.mark.asyncio
async def test_switch_unknown_family_returns_404(temp_state):
    from backend.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/models/switch",
            json={"family": "nonexistent", "profile": "reliable"},
        )

    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_switch_model_with_backend_override(temp_state):
    """Switching with backend=vulkan uses the -vulkan variant launcher."""
    import backend.config as cfg

    vulkan_data = {
        "family": "qwen-vulkan",
        "alias": "qwen3.6-27b-q6-vulkan",
        "model_name": "Qwen3.6 27B Heretic Q6_K (Vulkan)",
        "profile": "reliable",
        "context": 65536,
        "backend": "vulkan",
        "launcher_file": str(cfg.LAUNCHERS_DIR / "start-qwen-vulkan.sh"),
        "remote_start": "./start-qwen-vulkan.sh",
        "reasoning": False,
    }
    (cfg.ACCEPTED_DIR / "qwen-vulkan.json").write_text(json.dumps(vulkan_data, indent=2))
    (cfg.LAUNCHERS_DIR / "start-qwen-vulkan.sh").write_text(
        "#!/usr/bin/env bash\nGGML_VK_VISIBLE_DEVICES=0,1 exec ./build-vulkan/bin/llama-server\n"
    )
    (cfg.LAUNCHERS_DIR / "start-qwen-vulkan.sh").chmod(0o755)

    from backend.main import app

    with patch("backend.routes.switch.restart_llama_server") as mock_restart:
        mock_restart.return_value = True

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/models/switch",
                json={
                    "family": "qwen",
                    "profile": "reliable",
                    "backend": "vulkan",
                },
            )

    assert response.status_code == 200
    data = response.json()
    assert data["backend"] == "vulkan"
    assert "vulkan" in data["alias"]

    env_file = temp_state / "current-model.env"
    assert env_file.exists()
    content = env_file.read_text()
    assert "start-qwen-vulkan.sh" in content
