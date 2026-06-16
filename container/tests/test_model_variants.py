"""Tests for backend variant metadata helpers."""

from backend.model_variants import backend_variant_id, copy_backend_variant, migrate_backend_variant


def test_backend_variant_id_replaces_existing_backend_suffix():
    assert backend_variant_id("qwen-vulkan", "rocm") == "qwen-rocm"
    assert backend_variant_id("qwen-rocm", "vulkan") == "qwen-vulkan"
    assert backend_variant_id("qwen", "vulkan") == "qwen-vulkan"
    assert backend_variant_id("qwen-vulkan", "cuda") == "qwen-cuda"


def test_copy_backend_variant_preserves_model_source_and_changes_identity():
    source = {
        "family": "qwen-rocm",
        "alias": "qwen-rocm",
        "model_name": "Qwen",
        "backend": "rocm",
        "model_path": "/models/qwen.gguf",
        "hf_repo": "Org/Qwen",
        "hf_file": "qwen.gguf",
        "config": {"backend": "rocm", "visible_devices": "0", "tensor_split": "1,1"},
    }

    copied = copy_backend_variant(source, "vulkan")

    assert copied["family"] == "qwen-vulkan"
    assert copied["alias"] == "qwen-vulkan"
    assert copied["backend"] == "vulkan"
    assert copied["model_name"] == "Qwen (Vulkan)"
    assert copied["model_path"] == "/models/qwen.gguf"
    assert copied["hf_repo"] == "Org/Qwen"
    assert copied["hf_file"] == "qwen.gguf"
    assert copied["config"]["backend"] == "vulkan"
    assert copied["config"]["tensor_split"] == "1,1"


def test_migrate_backend_variant_adds_missing_suffix():
    source = {"family": "qwen", "alias": "qwen", "backend": "vulkan", "config": {}}

    migrated = migrate_backend_variant(source)

    assert migrated["family"] == "qwen-vulkan"
    assert migrated["alias"] == "qwen-vulkan"
    assert migrated["backend"] == "vulkan"
    assert migrated["config"]["backend"] == "vulkan"


def test_copy_backend_variant_cuda_label():
    source = {"family": "qwen", "alias": "qwen", "model_name": "Qwen", "backend": "rocm"}

    copied = copy_backend_variant(source, "cuda")

    assert copied["family"] == "qwen-cuda"
    assert copied["model_name"] == "Qwen (CUDA)"
    assert copied["config"]["backend"] == "cuda"
