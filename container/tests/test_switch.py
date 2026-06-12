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
async def test_switch_model_selects_llama_swap_model_without_restarting_service(temp_state):
    from backend.main import app

    with patch("backend.routes.switch.get_llama_swap_model_ids", return_value=["qwen3.6-27b-q6"]):
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
    assert data["status"] == "selected"
    assert data["family"] == "qwen"
    assert data["profile"] == "reliable"
    assert data["alias"] == "qwen3.6-27b-q6"

    selection_file = temp_state / "current-selection.json"
    assert selection_file.exists()
    selection = json.loads(selection_file.read_text())
    assert selection["model"] == "qwen3.6-27b-q6"
    assert selection["profile"] == "reliable"


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

    with patch("backend.routes.switch.get_llama_swap_model_ids", return_value=["qwen3.6-27b-q6-vulkan"]):
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
    assert data["alias"] == "qwen3.6-27b-q6-vulkan"

    selection = json.loads((temp_state / "current-selection.json").read_text())
    assert selection["model"] == "qwen3.6-27b-q6-vulkan"
