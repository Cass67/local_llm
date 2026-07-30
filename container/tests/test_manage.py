"""Tests for manage endpoints: inventory, detail, edit, delete, status."""

import json
from unittest.mock import MagicMock, patch

import pytest
from backend.main import app
from httpx import ASGITransport, AsyncClient


@pytest.fixture
def temp_state(tmp_path):
    accepted = tmp_path / "accepted"
    accepted.mkdir(parents=True)

    model_data = {
        "family": "qwen",
        "alias": "qwen-test-q6",
        "model_name": "Qwen Test Q6_K",
        "profile": "reliable",
        "backend": "rocm",
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

    import backend.config as cfg

    old_runs = cfg.RUNS_DIR
    old_llama = cfg.LLAMA_CPP_DIR
    cfg.RUNS_DIR = tmp_path
    cfg.ACCEPTED_DIR = accepted
    cfg.LLAMA_CPP_DIR = tmp_path
    yield tmp_path
    cfg.RUNS_DIR = old_runs
    cfg.ACCEPTED_DIR = old_runs / "accepted"
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

    updated = json.loads((temp_state / "accepted" / "qwen.json").read_text())
    assert updated["config"]["ctx"] == 65536
    assert updated["config"]["batch"] == 2048
    assert updated["config"]["backend"] == "vulkan"


@pytest.mark.asyncio
async def test_edit_model_saves_structured_mtp_config(temp_state):
    # mtp is stored flat (mtp_*); the nested {"mtp": {...}} form is legacy input only.
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.put(
            "/api/models/qwen",
            json={
                "mtp_enabled": True,
                "mtp_draft_n_max": 3,
                "mtp_draft_n_min": 1,
                "mtp_draft_p_min": 0.5,
            },
        )

    assert response.status_code == 200
    cfg = json.loads((temp_state / "accepted" / "qwen.json").read_text())["config"]
    assert "mtp" not in cfg
    assert cfg["mtp_enabled"] is True
    assert cfg["mtp_draft_n_max"] == 3
    assert cfg["mtp_draft_n_min"] == 1
    assert cfg["mtp_draft_p_min"] == 0.5


@pytest.mark.asyncio
async def test_edit_model_stores_raw_flags_in_metadata_only(temp_state):
    raw_flags = (
        "--spec-type draft-mtp --spec-draft-n-max 3 --spec-draft-n-min 1 --spec-draft-p-min 0.5"
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.put("/api/models/qwen", json={"flags": raw_flags})

    assert response.status_code == 200
    updated = json.loads((temp_state / "accepted" / "qwen.json").read_text())
    assert updated["config"]["flags"] == raw_flags


@pytest.mark.asyncio
async def test_edit_model_disabled_mtp_updates_metadata_only(temp_state):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        seeded = await client.put(
            "/api/models/qwen",
            json={
                "mtp_enabled": True,
                "mtp_draft_n_max": 3,
                "mtp_draft_n_min": 1,
                "mtp_draft_p_min": 0.5,
            },
        )
        assert seeded.status_code == 200

        response = await client.put("/api/models/qwen", json={"mtp_enabled": False})

    assert response.status_code == 200
    cfg = json.loads((temp_state / "accepted" / "qwen.json").read_text())["config"]
    # Disabling flips the flag without discarding the tuned draft values.
    assert cfg["mtp_enabled"] is False
    assert cfg["mtp_draft_n_max"] == 3
    assert cfg["mtp_draft_n_min"] == 1
    assert cfg["mtp_draft_p_min"] == 0.5


@pytest.mark.asyncio
async def test_delete_models_removes_accepted_metadata_by_family(temp_state):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/models/delete",
            json={"repos": ["qwen"]},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["results"] == [{"repo": "qwen", "status": "deleted", "family": "qwen"}]
    assert not (temp_state / "accepted" / "qwen.json").exists()


@pytest.mark.asyncio
async def test_delete_models_removes_accepted_metadata_by_alias(temp_state):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/models/delete",
            json={"repos": ["qwen-test-q6"]},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["results"] == [{"repo": "qwen-test-q6", "status": "deleted", "family": "qwen"}]
    assert not (temp_state / "accepted" / "qwen.json").exists()


@pytest.mark.asyncio
async def test_delete_models_does_not_call_remote_only_model_manager(temp_state):
    with patch("backend.cli.subprocess.run") as run:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/models/delete",
                json={"repos": ["qwen"]},
            )

    assert response.status_code == 200
    run.assert_not_called()


@pytest.mark.asyncio
async def test_status_returns_full_state(temp_state):
    with (
        patch(
            "backend.routes.manage.list_active",
            return_value=[{"family": "qwen3.6-27b-q6", "model": "qwen3.6-27b-q6", "port": 8080}],
        ),
        patch("backend.routes.manage.subprocess.run") as mock_run,
    ):
        mock_run.return_value = MagicMock(stdout="", returncode=1)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/status")

    assert response.status_code == 200
    data = response.json()
    assert data["target"] == "local"
    assert data["accepted_count"] == 1
    assert data["running"]["status"] == "active"
