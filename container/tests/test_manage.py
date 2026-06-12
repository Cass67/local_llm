"""Tests for manage endpoints: inventory, detail, edit, delete, status."""

import json
import pytest
from unittest.mock import patch, MagicMock
from httpx import ASGITransport, AsyncClient
from backend.main import app


@pytest.fixture
def temp_state(tmp_path):
    accepted = tmp_path / "accepted"
    launchers = tmp_path / "launchers"
    accepted.mkdir(parents=True)
    launchers.mkdir(parents=True)

    model_data = {
        "family": "qwen",
        "alias": "qwen-test-q6",
        "model_name": "Qwen Test Q6_K",
        "profile": "reliable",
        "backend": "rocm",
        "launcher_file": str(launchers / "start-qwen.sh"),
        "remote_start": "./start-qwen.sh",
        "reasoning": True,
        "config": {
            "quant": "Q6_K",
            "batch": 4096,
            "ubatch": 256,
            "ngl": 999,
            "ctx": 131072,
            "visible_devices": "0,1",
        },
    }
    (accepted / "qwen.json").write_text(json.dumps(model_data, indent=2))
    (launchers / "start-qwen.sh").write_text("#!/usr/bin/env bash\necho ok\n")
    (launchers / "start-qwen.sh").chmod(0o755)

    import backend.config as cfg

    old_runs = cfg.RUNS_DIR
    old_llama = cfg.LLAMA_CPP_DIR
    cfg.RUNS_DIR = tmp_path
    cfg.ACCEPTED_DIR = accepted
    cfg.LAUNCHERS_DIR = launchers
    cfg.LLAMA_CPP_DIR = tmp_path
    yield tmp_path
    cfg.RUNS_DIR = old_runs
    cfg.ACCEPTED_DIR = old_runs / "accepted"
    cfg.LAUNCHERS_DIR = old_runs / "launchers"
    cfg.LLAMA_CPP_DIR = old_llama


@pytest.mark.asyncio
async def test_inventory_returns_disk_models():
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = (
        '{"repo":"TheBloke/qwen-GGUF","path":"/cache/qwen","file":"qwen.Q6_K.gguf","disk_gb":"12.3","gguf":"yes"}\n'
        '{"repo":"TheBloke/llama-GGUF","path":"/cache/llama","file":"llama.Q4_K_M.gguf","disk_gb":"5.1","gguf":"yes"}\n'
    )
    mock_result.stderr = ""

    with patch("backend.routes.manage.subprocess.run", return_value=mock_result):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/inventory")

    assert response.status_code == 200
    data = response.json()
    assert len(data["models"]) == 2
    assert data["models"][0]["repo"] == "TheBloke/llama-GGUF"


@pytest.mark.asyncio
async def test_detail_returns_full_metadata(temp_state):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/models/qwen/detail")

    assert response.status_code == 200
    data = response.json()
    assert data["family"] == "qwen"
    assert data["alias"] == "qwen-test-q6"
    assert data["config"]["ctx"] == 131072
    assert data["reasoning"] is True


@pytest.mark.asyncio
async def test_detail_unknown_family_returns_404(temp_state):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/models/nonexistent/detail")

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_edit_model_updates_config(temp_state):
    mock_launcher = MagicMock()
    mock_launcher.returncode = 0
    mock_launcher.stdout = "ok"
    mock_launcher.stderr = ""

    with patch("backend.cli.subprocess.run", return_value=mock_launcher):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.put(
                "/api/models/qwen",
                json={
                    "ctx": 65536,
                    "batch": 2048,
                    "backend": "vulkan",
                },
            )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"

    # Verify file was updated
    updated = json.loads((temp_state / "accepted" / "qwen.json").read_text())
    assert updated["config"]["ctx"] == 65536
    assert updated["config"]["batch"] == 2048
    assert updated["config"]["backend"] == "vulkan"


@pytest.mark.asyncio
async def test_delete_models(temp_state):
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = ""
    mock_result.stderr = ""

    with patch("backend.cli.subprocess.run", return_value=mock_result):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/models/delete",
                json={
                    "repos": ["TheBloke/qwen-GGUF"],
                },
            )

    assert response.status_code == 200
    data = response.json()
    assert len(data["results"]) == 1


@pytest.mark.asyncio
async def test_status_returns_full_state(temp_state):
    with (
        patch("backend.routes.manage.detect_running_model", return_value={"status": "active", "family": "qwen3.6-27b-q6", "ctx": None}),
        patch("backend.routes.manage.subprocess.run") as mock_run,
    ):
        # mock for pgrep (downloads)
        mock_run.return_value = MagicMock(stdout="", returncode=1)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/status")

    assert response.status_code == 200
    data = response.json()
    assert data["target"] == "local"
    assert data["accepted_count"] == 1
    assert data["running"]["status"] == "active"
