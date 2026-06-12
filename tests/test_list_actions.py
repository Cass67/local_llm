from __future__ import annotations

import pytest
from scripts.model_manager.tui_helpers import (
    build_effective_command,
    get_model_metadata,
)


@pytest.fixture
def accepted_data():
    return {
        "repo": "Qwen/Qwen3.6-27B",
        "profiles": {
            "balanced": {
                "ctx": 16384,
                "flags": "--reasoning",
            }
        },
        "launcher": "~/.local/share/local_llm/launchers/qwen3.6-27b.sh",
    }


def test_get_model_metadata_returns_data(accepted_data):
    result = get_model_metadata(accepted_data)
    assert result["repo"] == "Qwen/Qwen3.6-27B"
    assert "balanced" in result["profiles"]


def test_build_effective_command_includes_repo_and_flags():
    cmd = build_effective_command(
        repo="Qwen/Qwen3.6-27B",
        profile="balanced",
        ctx=16384,
        extra_flags="--reasoning --batch 4096",
    )
    assert "Qwen/Qwen3.6-27B" in cmd
    assert "--ctx-size 16384" in cmd
    assert "--reasoning" in cmd


def test_build_effective_command_respects_profile_ctx():
    cmd = build_effective_command(
        repo="test/repo",
        profile="speed",
        ctx=8192,
        extra_flags="",
    )
    assert "--ctx-size 8192" in cmd


def test_build_effective_command_handles_empty_flags():
    cmd = build_effective_command(
        repo="test/repo",
        profile="tiny",
        ctx=4096,
        extra_flags="",
    )
    assert "--ctx-size 4096" in cmd
