"""Tests for backend variant copy/migration APIs."""

import json

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture
def temp_state(tmp_path, monkeypatch):
    accepted = tmp_path / "accepted"
    accepted.mkdir(parents=True)
    (accepted / "qwen.json").write_text(
        json.dumps(
            {
                "family": "qwen",
                "alias": "qwen",
                "model_name": "Qwen",
                "backend": "vulkan",
                "model_path": "/models/qwen.gguf",
                "config": {"backend": "vulkan", "tensor_split": "1,1"},
            }
        )
    )
    import backend.config as cfg

    monkeypatch.setattr(cfg, "RUNS_DIR", tmp_path)
    monkeypatch.setattr(cfg, "ACCEPTED_DIR", accepted)
    return tmp_path


@pytest.mark.asyncio
async def test_copy_backend_creates_opposite_backend_metadata(temp_state):
    from backend.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/models/qwen/copy-backend", json={"backend": "rocm"})

    assert response.status_code == 200
    assert response.json()["family"] == "qwen-rocm"
    copied = json.loads((temp_state / "accepted" / "qwen-rocm.json").read_text())
    assert copied["model_path"] == "/models/qwen.gguf"
    assert copied["backend"] == "rocm"
    assert copied["config"]["backend"] == "rocm"


@pytest.mark.asyncio
async def test_copy_backend_creates_cuda_metadata(temp_state):
    from backend.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/models/qwen/copy-backend", json={"backend": "cuda"})

    assert response.status_code == 200
    assert response.json()["family"] == "qwen-cuda"
    copied = json.loads((temp_state / "accepted" / "qwen-cuda.json").read_text())
    assert copied["model_path"] == "/models/qwen.gguf"
    assert copied["backend"] == "cuda"
    assert copied["config"]["backend"] == "cuda"


@pytest.mark.asyncio
async def test_migrate_backend_names_writes_explicit_suffix(temp_state):
    from backend.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/models/migrate-backend-names")

    assert response.status_code == 200
    assert response.json()["migrated"] == ["qwen-vulkan"]
    assert not (temp_state / "accepted" / "qwen.json").exists()
    assert (temp_state / "accepted" / "qwen-vulkan.json").exists()


@pytest.mark.asyncio
async def test_migrate_backend_names_updates_current_selection(temp_state):
    (temp_state / "current-selection.json").write_text(
        json.dumps({"model": "qwen", "family": "qwen"})
    )
    from backend.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/models/migrate-backend-names")

    assert response.status_code == 200
    selection = json.loads((temp_state / "current-selection.json").read_text())
    assert selection["model"] == "qwen-vulkan"
    assert selection["family"] == "qwen-vulkan"
