"""Tests for switch endpoint."""

import json
import pytest
from unittest.mock import patch

from httpx import ASGITransport, AsyncClient


@pytest.fixture
def temp_state(tmp_path, monkeypatch):
    accepted = tmp_path / "accepted"
    accepted.mkdir(parents=True)
    model_file = tmp_path / "models--Test--Qwen" / "snapshots" / "abc" / "qwen.gguf"
    model_file.parent.mkdir(parents=True)
    model_file.write_text("fake")

    model_data = {
        "family": "qwen",
        "alias": "qwen3.6-27b-q6",
        "model_name": "Qwen3.6 27B Heretic Q6_K",
        "profile": "reliable",
        "context": 131072,
        "backend": "rocm",
        "reasoning": False,
        "repo": "Test/Qwen",
        "hf_repo": "Test/Qwen",
        "hf_file": "qwen.gguf",
        "config": {"ctx": 131072, "batch": 4096, "ubatch": 256, "ngl": 999},
    }
    (accepted / "qwen.json").write_text(json.dumps(model_data, indent=2))

    import backend.config as cfg

    monkeypatch.setattr(cfg, "RUNS_DIR", tmp_path)
    monkeypatch.setattr(cfg, "ACCEPTED_DIR", accepted)
    monkeypatch.setattr(cfg, "LLAMA_CPP_DIR", tmp_path)
    monkeypatch.setattr(cfg, "MODELS_CACHE_DIR", tmp_path)
    return tmp_path


@pytest.mark.asyncio
async def test_switch_model_writes_project_runner_state(temp_state):
    from backend.main import app

    with (
        patch("backend.routes.switch.DockerRunner") as runner_cls,
        patch("backend.routes.switch._wait_for_runner_ready", return_value=True) as wait_ready,
    ):
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
    assert data["status"] == "loaded"
    assert data["family"] == "qwen"
    assert data["profile"] == "reliable"
    assert data["alias"] == "qwen3.6-27b-q6"
    runner_cls.return_value.launch.assert_called_once()
    wait_ready.assert_called_once_with(runner_cls.return_value)
    launched_metadata = runner_cls.return_value.launch.call_args.args[0]
    assert launched_metadata["alias"] == "qwen3.6-27b-q6"

    runner_file = temp_state / "current-runner.json"
    assert runner_file.exists()
    runner = json.loads(runner_file.read_text())
    assert runner["model"] == "qwen3.6-27b-q6"
    assert runner["container"]["name"] == "local-llm-runner"
    assert runner["container"]["command"][:4] == [
        "llama-server",
        "--port",
        "8080",
        "-m",
    ]
    assert runner["container"]["command"][4].endswith("models--Test--Qwen/snapshots/abc/qwen.gguf")

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
        "reasoning": False,
        "model_path": "/models/qwen-vulkan.gguf",
        "config": {"backend": "vulkan"},
    }
    (cfg.ACCEPTED_DIR / "qwen-vulkan.json").write_text(json.dumps(vulkan_data, indent=2))

    from backend.main import app

    with (
        patch("backend.routes.switch.DockerRunner"),
        patch("backend.routes.switch._wait_for_runner_ready", return_value=True),
    ):
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


@pytest.mark.asyncio
async def test_switch_model_with_cuda_backend_override(temp_state):
    """Switching with backend=cuda uses the -cuda variant launcher."""
    import backend.config as cfg

    cuda_data = {
        "family": "qwen-cuda",
        "alias": "qwen3.6-27b-q6-cuda",
        "model_name": "Qwen3.6 27B Heretic Q6_K (CUDA)",
        "profile": "reliable",
        "context": 65536,
        "backend": "cuda",
        "reasoning": False,
        "model_path": "/models/qwen-cuda.gguf",
        "config": {"backend": "cuda"},
    }
    (cfg.ACCEPTED_DIR / "qwen-cuda.json").write_text(json.dumps(cuda_data, indent=2))

    from backend.main import app

    with (
        patch("backend.routes.switch.DockerRunner"),
        patch("backend.routes.switch._wait_for_runner_ready", return_value=True),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/models/switch",
                json={
                    "family": "qwen",
                    "profile": "reliable",
                    "backend": "cuda",
                },
            )

    assert response.status_code == 200
    data = response.json()
    assert data["backend"] == "cuda"
    assert data["alias"] == "qwen3.6-27b-q6-cuda"

    selection = json.loads((temp_state / "current-selection.json").read_text())
    assert selection["model"] == "qwen3.6-27b-q6-cuda"
