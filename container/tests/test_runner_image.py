"""Tests for project-owned llama.cpp runner image."""

from pathlib import Path


def test_runner_dockerfile_uses_project_owned_llama_cpp_base():
    dockerfile = Path(__file__).resolve().parents[2] / "runner" / "Dockerfile"
    text = dockerfile.read_text()

    assert "ghcr.io/mostlygeek/llama-swap" not in text
    assert "llama.cpp" in text
    assert "LLAMA_VULKAN=1" in text
    assert "llama-server" in text
