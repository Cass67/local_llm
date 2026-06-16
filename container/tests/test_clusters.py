"""Tests for cluster CRUD and GPU-index derivation."""

import pytest

from backend.clusters import (
    create_cluster,
    delete_cluster,
    get_cluster,
    list_clusters,
    tensor_split_for,
    visible_devices_for,
    list_active,
    read_active,
    write_active,
    remove_active,
)
from backend.gpu_inventory import GpuInfo


def _gpu(pci_id, vendor, rocm=None, cuda=None, vk=None):
    return GpuInfo(
        pci_id=pci_id,
        vendor=vendor,
        model_name="GPU",
        vram_mb=20480,
        rocm_index=rocm,
        cuda_index=cuda,
        vulkan_index=vk,
    )


@pytest.fixture
def temp_state(tmp_path, monkeypatch):
    monkeypatch.setattr("backend.clusters.config.RUNS_DIR", tmp_path)
    monkeypatch.setattr("backend.clusters._allocate_port", lambda existing: 8080 + len(existing))
    return tmp_path


INVENTORY = [
    _gpu("0000:03:00.0", "amd", rocm=0, vk=0),
    _gpu("0000:04:00.0", "amd", rocm=1, vk=1),
    _gpu("0000:05:00.0", "nvidia", cuda=0, vk=2),
]


def test_create_and_get_cluster(temp_state):
    _ = temp_state
    c = create_cluster("test cluster", ["0000:03:00.0"], "rocm", INVENTORY)
    assert c.name == "test cluster"
    assert c.backend == "rocm"
    assert c.gpu_pci_ids == ["0000:03:00.0"]
    assert c.port == 8080

    fetched = get_cluster(c.id)
    assert fetched is not None
    assert fetched.id == c.id


def test_list_clusters(temp_state):
    _ = temp_state
    create_cluster("A", ["0000:03:00.0"], "rocm", INVENTORY)
    create_cluster("B", ["0000:04:00.0"], "vulkan", INVENTORY)
    clusters = list_clusters()
    assert len(clusters) == 2
    names = {c.name for c in clusters}
    assert names == {"A", "B"}


def test_delete_cluster(temp_state):
    _ = temp_state
    c = create_cluster("to delete", ["0000:03:00.0"], "rocm", INVENTORY)
    delete_cluster(c.id)
    assert get_cluster(c.id) is None


def test_rocm_rejects_nvidia_gpu(temp_state):
    _ = temp_state
    with pytest.raises(ValueError, match="vendor"):
        create_cluster("bad", ["0000:05:00.0"], "rocm", INVENTORY)


def test_cuda_rejects_amd_gpu(temp_state):
    _ = temp_state
    with pytest.raises(ValueError, match="vendor"):
        create_cluster("bad", ["0000:03:00.0"], "cuda", INVENTORY)


def test_vulkan_allows_mixed_vendors(temp_state):
    _ = temp_state
    c = create_cluster("mixed", ["0000:03:00.0", "0000:05:00.0"], "vulkan", INVENTORY)
    assert c.backend == "vulkan"
    assert len(c.gpu_pci_ids) == 2


def test_invalid_backend_rejected(temp_state):
    _ = temp_state
    with pytest.raises(ValueError, match="backend"):
        create_cluster("bad", ["0000:03:00.0"], "metal", INVENTORY)


def test_visible_devices_rocm(temp_state):
    _ = temp_state
    c = create_cluster("dual amd", ["0000:03:00.0", "0000:04:00.0"], "rocm", INVENTORY)
    result = visible_devices_for(c, INVENTORY)
    assert result == "0,1"


def test_visible_devices_vulkan_mixed(temp_state):
    _ = temp_state
    c = create_cluster("mixed", ["0000:03:00.0", "0000:05:00.0"], "vulkan", INVENTORY)
    result = visible_devices_for(c, INVENTORY)
    assert result == "0,2"


def test_visible_devices_cuda(temp_state):
    _ = temp_state
    c = create_cluster("nvidia", ["0000:05:00.0"], "cuda", INVENTORY)
    result = visible_devices_for(c, INVENTORY)
    assert result == "0"


def test_tensor_split_for():
    assert tensor_split_for(1) == "1"
    assert tensor_split_for(2) == "1,1"
    assert tensor_split_for(3) == "1,1,1"


def test_active_crud(temp_state):
    _ = temp_state
    write_active("abc123", {"model": "qwen", "port": 8080})
    data = read_active("abc123")
    assert data is not None
    assert data["model"] == "qwen"

    all_active = list_active()
    assert len(all_active) == 1

    remove_active("abc123")
    assert read_active("abc123") is None
    assert list_active() == []
