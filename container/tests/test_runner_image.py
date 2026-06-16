"""Tests for project-owned llama.cpp runner images."""

from pathlib import Path

RUNNER_DIR = Path(__file__).resolve().parents[2] / "runner"


def test_vulkan_dockerfile_uses_project_owned_llama_cpp_base():
    text = (RUNNER_DIR / "vulkan" / "Dockerfile").read_text()

    assert "ghcr.io/mostlygeek/llama-swap" not in text
    assert "llama.cpp" in text
    assert "LLAMA_VULKAN=1" in text
    assert "llama-server" in text


def test_rocm_dockerfile_compiles_with_hip():
    text = (RUNNER_DIR / "rocm" / "Dockerfile").read_text()

    assert "llama.cpp" in text
    assert "GGML_HIP=ON" in text
    assert "llama-server" in text


def test_cuda_dockerfile_compiles_with_cuda():
    text = (RUNNER_DIR / "cuda" / "Dockerfile").read_text()

    assert "llama.cpp" in text
    assert "GGML_CUDA=ON" in text
    assert "llama-server" in text
